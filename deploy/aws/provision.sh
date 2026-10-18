#!/usr/bin/env bash
# Find or create what the On-call Brain box needs on AWS, all tagged Project=graphhacks (docs/DEPLOY.md section E):
# an IAM role for the box, a private S3 bucket for code tarballs, a security group that opens only 80 and 443, an
# Elastic IP, and one t4g.small on Amazon Linux 2023 arm64 with no SSH and no key pair.
#   deploy/aws/provision.sh --dry-run   print the plan, the monthly estimate and EC2's dry-run answers; change nothing
#   deploy/aws/provision.sh [--yes]     print the plan, ask "Create these? [y/N]" (--yes skips the question), create
# Safe to run again: it creates only what is missing (and starts the box if it is stopped). Next: deploy/aws/deploy.sh.
set -euo pipefail

REGION=ap-south-1
PROJECT=graphhacks        # every resource gets the tag Project=$PROJECT
NAME=oncall-brain         # name prefix: $NAME-host (role + instance profile), $NAME-web, $NAME-ip, $NAME-box
SSM_PATH=/graphhacks      # the box may read the parameters under this path and nothing else
INSTANCE_TYPE=t4g.small   # Graviton (ARM), 2 vCPU, 2 GiB
DISK_GB=20
AMI_PARAM=/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64
TARBALL_DAYS=14           # the bucket deletes code tarballs older than this
HOURS=730                 # hours in an average month, for the estimate
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

ROLE=$NAME-host SG_NAME=$NAME-web EIP_NAME=$NAME-ip BOX=$NAME-box
TAG="{Key=Project,Value=$PROJECT}"

DRY=0 YES=0
for arg in "$@"; do
  case $arg in
    --dry-run) DRY=1 ;;
    --yes) YES=1 ;;
    *) echo "usage: $0 [--dry-run] [--yes]" >&2; exit 2 ;;
  esac
done

ec2() { aws ec2 "$@" --region "$REGION"; }
iam() { aws iam "$@" --region "$REGION"; }
none() { [ -z "$1" ] || [ "$1" = None ]; }  # `--output text` prints None for a missing value
row() { printf '  %-16s %-40s %s\n' "$1" "$2" "$3"; }

# ---- What exists (read-only calls) ------------------------------------------------------------------------------
ACCOUNT=$(aws sts get-caller-identity --region "$REGION" --query Account --output text)
BUCKET=$NAME-$ACCOUNT-$REGION
VPC=$(ec2 describe-vpcs --filters Name=is-default,Values=true --query 'Vpcs[0].VpcId' --output text)
none "$VPC" && { echo "No default VPC in $REGION." >&2; exit 1; }
AMI=$(aws ssm get-parameter --region "$REGION" --name "$AMI_PARAM" --query Parameter.Value --output text)
read -r AMI_NAME ROOT_DEV < <(ec2 describe-images --image-ids "$AMI" \
  --query 'Images[0].[Name,RootDeviceName]' --output text)
AZS=$(ec2 describe-instance-type-offerings --location-type availability-zone \
  --filters "Name=instance-type,Values=$INSTANCE_TYPE" --query 'sort(InstanceTypeOfferings[].Location)' --output text)
none "$AZS" && { echo "$INSTANCE_TYPE is not offered in $REGION." >&2; exit 1; }
read -r SUBNET SUBNET_AZ < <(ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC" Name=default-for-az,Values=true \
  "Name=availability-zone,Values=$(tr '\t' ',' <<<"$AZS")" \
  --query 'sort_by(Subnets,&AvailabilityZone)[0].[SubnetId,AvailabilityZone]' --output text)

ROLE_ARN=$(iam get-role --role-name "$ROLE" --query Role.Arn --output text 2>/dev/null || true)
read -r PROFILE_ARN PROFILE_ROLE < <(iam get-instance-profile --instance-profile-name "$ROLE" \
  --query '[InstanceProfile.Arn,InstanceProfile.Roles[0].RoleName]' --output text 2>/dev/null || echo None None)
BUCKET_OK=""
if aws s3api head-bucket --region "$REGION" --bucket "$BUCKET" --expected-bucket-owner "$ACCOUNT" >/dev/null 2>&1; then
  BUCKET_OK=yes
fi
SG_ID=$(ec2 describe-security-groups --filters "Name=vpc-id,Values=$VPC" "Name=group-name,Values=$SG_NAME" \
  --query 'SecurityGroups[0].GroupId' --output text)
read -r EIP_ALLOC EIP EIP_INSTANCE < <(ec2 describe-addresses \
  --filters "Name=tag:Name,Values=$EIP_NAME" "Name=tag:Project,Values=$PROJECT" \
  --query 'Addresses[0].[AllocationId,PublicIp,InstanceId]' --output text)
read -r INSTANCE STATE < <(ec2 describe-instances \
  --filters "Name=tag:Name,Values=$BOX" "Name=tag:Project,Values=$PROJECT" \
  Name=instance-state-name,Values=pending,running,stopping,stopped \
  --query 'Reservations[0].Instances[0].[InstanceId,State.Name]' --output text)
# The AWS-managed key that encrypts SecureString parameters (it exists once any SecureString was written).
SSM_KEY=$(aws kms list-aliases --region "$REGION" --query "Aliases[?AliasName=='alias/aws/ssm'].TargetKeyId | [0]" \
  --output text)
none "$SSM_KEY" && SSM_KEY='*'  # not created yet: any key, still only when SSM asks (kms:ViaService below)

# ---- The plan ---------------------------------------------------------------------------------------------------
TODO=()  # what this run would create or start
echo "On-call Brain on AWS: account $ACCOUNT, $REGION, default VPC $VPC$([ "$DRY" = 1 ] && echo ', dry run')"
echo
if [ -n "$ROLE_ARN" ] && ! none "$PROFILE_ROLE"; then
  row "IAM role" "$ROLE" "exists (policy refreshed on a real run)"
else
  row "IAM role" "$ROLE" "create: role + instance profile; SSM core, read s3://$BUCKET/$NAME/* and $SSM_PATH/*"
  TODO+=("IAM role $ROLE")
fi
if [ -n "$BUCKET_OK" ]; then
  row "S3 bucket" "$BUCKET" "exists"
else
  row "S3 bucket" "$BUCKET" "create: private, SSE-S3, tarballs expire after $TARBALL_DAYS days"
  TODO+=("S3 bucket $BUCKET")
fi
if none "$SG_ID"; then
  row "security group" "$SG_NAME" "create: in tcp/80, tcp/443, udp/443 from anywhere; nothing else"
  TODO+=("security group $SG_NAME")
else
  RULES=$(ec2 describe-security-groups --group-ids "$SG_ID" \
    --query 'SecurityGroups[0].IpPermissions[].[IpProtocol,FromPort]' --output text | tr '\t' '/' | tr '\n' ' ')
  row "security group" "$SG_NAME" "exists $SG_ID: in $RULES"
fi
if none "$EIP_ALLOC"; then
  row "Elastic IP" "$EIP_NAME" "create (keeps the sslip.io name and the certificate across stop/start)"
  TODO+=("Elastic IP $EIP_NAME")
else
  row "Elastic IP" "$EIP_NAME" "exists $EIP"
fi
if none "$INSTANCE"; then
  row "EC2 instance" "$BOX" "create: $INSTANCE_TYPE, $AMI, $SUBNET ($SUBNET_AZ)"
  row "" "" "$DISK_GB GB gp3 encrypted, IMDSv2 only (hop limit 1), no key pair"
  TODO+=("EC2 instance $BOX ($INSTANCE_TYPE)")
else
  row "EC2 instance" "$BOX" "exists $INSTANCE ($STATE)"
  [[ $STATE == stop* ]] && TODO+=("start $INSTANCE")
fi
if none "$EIP_ALLOC" || none "$INSTANCE" || [ "$EIP_INSTANCE" != "$INSTANCE" ]; then
  row "association" "$EIP_NAME -> $BOX" "associate"
fi
echo
echo "  AMI $AMI_NAME (from $AMI_PARAM)"
echo "  $INSTANCE_TYPE is offered in: $(tr '\t' ' ' <<<"$AZS")"

# ---- Monthly estimate (live Pricing API; the Pricing endpoint is in us-east-1) -----------------------------------
price() {  # <service-code> <field=value>...: the on-demand USD price per unit
  local filters=() kv
  for kv in "${@:2}"; do filters+=("Type=TERM_MATCH,Field=${kv%%=*},Value=${kv#*=}"); done
  aws pricing get-products --region us-east-1 --service-code "$1" --filters "${filters[@]}" \
      --query 'PriceList[0]' --output text 2>/dev/null |
    python3 -c 'import json,sys; t=next(iter(json.load(sys.stdin)["terms"]["OnDemand"].values()))
print(float(next(iter(t["priceDimensions"].values()))["pricePerUnit"]["USD"]))' 2>/dev/null
}
SRC="live, AWS Pricing API"
EC2_H=$(price AmazonEC2 "instanceType=$INSTANCE_TYPE" "regionCode=$REGION" operatingSystem=Linux tenancy=Shared \
  preInstalledSw=NA capacitystatus=Used) || { EC2_H=0.0112; SRC="AWS_GUIDE.md prices, Pricing API unreachable"; }
IP_H=$(price AmazonVPC "regionCode=$REGION" "usagetype=APS3-PublicIPv4:InUseAddress") || IP_H=0.005  # APS3 = Mumbai
GP3=$(price AmazonEC2 "regionCode=$REGION" volumeApiName=gp3 productFamily=Storage) || GP3=0.0912
echo
echo "Monthly estimate, on demand ($SRC):"
awk -v e="$EC2_H" -v i="$IP_H" -v g="$GP3" -v h="$HOURS" -v d="$DISK_GB" -v t="$INSTANCE_TYPE" 'BEGIN {
  line(t, sprintf("$%s/h x %d h", e, h), e * h)
  line("public IPv4", sprintf("$%s/h x %d h", i, h), i * h)
  line("gp3 disk", sprintf("$%s/GB-month x %d GB", g, d), g * d)
  line("total", "", e * h + i * h + g * d)
  printf "  S3 and standard SSM parameters cost cents. Stopped, the box costs ~$%.2f (disk + idle Elastic IP).\n", g * d + i * h
}
function line(what, how, usd) { printf "  %-12s %-26s $%6.2f\n", what, how, usd }'

# ---- Arguments shared by the dry-run check and the real launch ----------------------------------------------------
RUN_ARGS=(--image-id "$AMI" --instance-type "$INSTANCE_TYPE" --count 1 --subnet-id "$SUBNET"
  --metadata-options "HttpTokens=required,HttpPutResponseHopLimit=1,HttpEndpoint=enabled"
  --block-device-mappings "DeviceName=$ROOT_DEV,Ebs={VolumeSize=$DISK_GB,VolumeType=gp3,Encrypted=true,DeleteOnTermination=true}"
  --user-data "file://$HERE/bootstrap-al2023.sh"
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$BOX},$TAG]"
  "ResourceType=volume,Tags=[{Key=Name,Value=$BOX},$TAG]"
  "ResourceType=network-interface,Tags=[{Key=Name,Value=$BOX},$TAG]")

if [ "$DRY" = 1 ]; then
  FAILED=0
  dry() {  # <label> <ec2 subcommand + args>: EC2 answers DryRunOperation when the real call would succeed
    local label=$1 out
    shift
    out=$(aws ec2 "$@" --region "$REGION" --dry-run 2>&1) || true
    if [[ $out == *DryRunOperation* ]]; then echo "  ok    $label"; else echo "  FAIL  $label: ${out#*operation: }"; FAILED=1; fi
  }
  echo
  echo "EC2 dry-run checks (DryRunOperation = the real call would succeed):"
  EXTRA=() NOTE=""
  if none "$SG_ID"; then NOTE+=" the VPC's default security group,"; else EXTRA+=(--security-group-ids "$SG_ID"); fi
  if none "$PROFILE_ROLE"; then NOTE+=" no instance profile,"; else EXTRA+=(--iam-instance-profile "Name=$ROLE"); fi
  dry "run-instances${NOTE:+ (with${NOTE%,}: they do not exist yet)}" run-instances "${RUN_ARGS[@]}" "${EXTRA[@]}"
  none "$SG_ID" && dry "create-security-group $SG_NAME" create-security-group --group-name "$SG_NAME" \
    --description "On-call Brain: HTTP and HTTPS only" --vpc-id "$VPC"
  none "$EIP_ALLOC" && dry "allocate-address" allocate-address --domain vpc
  echo
  echo "Dry run: nothing was created.$([ ${#TODO[@]} = 0 ] && echo ' Everything exists already.')"
  row "instance" "${INSTANCE/None/(created by a real run)}" ""
  row "Elastic IP" "${EIP:-(allocated by a real run)}" ""
  row "domain" "$([ -n "$EIP" ] && echo "${EIP//./-}.sslip.io" || echo '<elastic-ip-with-dashes>.sslip.io')" ""
  exit "$FAILED"
fi

# ---- Create what is missing ---------------------------------------------------------------------------------------
if [ ${#TODO[@]} -gt 0 ] && [ "$YES" = 0 ]; then
  echo
  echo "To create or start:"
  printf '  - %s\n' "${TODO[@]}"
  read -rp "Create these? [y/N] " answer || answer=""
  [[ $answer == [yY]* ]] || { echo "Nothing created."; exit 1; }
fi
echo

# IAM: the role the box runs as. Inline policy: its own code tarballs, its own settings, and decrypting them via SSM.
# AmazonSSMManagedInstanceCore allows ssm:GetParameter(s) on every parameter in the account (and the aws/ssm key lets
# SSM decrypt any of them), so the Deny keeps the box to $SSM_PATH. Run Command and Session Manager do not use these.
POLICY=$(cat <<EOF
{"Version": "2012-10-17", "Statement": [
  {"Sid": "CodeTarballs", "Effect": "Allow", "Action": "s3:GetObject", "Resource": "arn:aws:s3:::$BUCKET/$NAME/*"},
  {"Sid": "Settings", "Effect": "Allow",
   "Action": ["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath"],
   "Resource": ["arn:aws:ssm:$REGION:$ACCOUNT:parameter$SSM_PATH", "arn:aws:ssm:$REGION:$ACCOUNT:parameter$SSM_PATH/*"]},
  {"Sid": "DecryptSettings", "Effect": "Allow", "Action": "kms:Decrypt",
   "Resource": "arn:aws:kms:$REGION:$ACCOUNT:key/$SSM_KEY",
   "Condition": {"StringEquals": {"kms:ViaService": "ssm.$REGION.amazonaws.com"}}},
  {"Sid": "OnlyOurParameters", "Effect": "Deny",
   "Action": ["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath"],
   "NotResource": ["arn:aws:ssm:$REGION:$ACCOUNT:parameter$SSM_PATH", "arn:aws:ssm:$REGION:$ACCOUNT:parameter$SSM_PATH/*"]}
]}
EOF
)
if [ -z "$ROLE_ARN" ]; then
  echo "Creating IAM role $ROLE"
  iam create-role --role-name "$ROLE" --tags "Key=Project,Value=$PROJECT" \
    --description "On-call Brain box: SSM Run Command, its code tarballs, its $SSM_PATH settings" \
    --assume-role-policy-document \
    '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}' \
    >/dev/null
fi
iam attach-role-policy --role-name "$ROLE" --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
iam put-role-policy --role-name "$ROLE" --policy-name "$NAME-host" --policy-document "$POLICY"
if none "$PROFILE_ARN"; then
  echo "Creating instance profile $ROLE"
  iam create-instance-profile --instance-profile-name "$ROLE" --tags "Key=Project,Value=$PROJECT" >/dev/null
fi
if none "$PROFILE_ROLE"; then
  iam add-role-to-instance-profile --instance-profile-name "$ROLE" --role-name "$ROLE"
fi

# S3: settings are re-applied on every run, so a bucket left half-configured by an interrupted run gets fixed.
if [ -z "$BUCKET_OK" ]; then
  echo "Creating S3 bucket $BUCKET"
  aws s3api create-bucket --region "$REGION" --bucket "$BUCKET" \
    --create-bucket-configuration "LocationConstraint=$REGION" >/dev/null
fi
aws s3api put-public-access-block --region "$REGION" --bucket "$BUCKET" --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-bucket-encryption --region "$REGION" --bucket "$BUCKET" --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
aws s3api put-bucket-lifecycle-configuration --region "$REGION" --bucket "$BUCKET" --lifecycle-configuration \
  "{\"Rules\":[{\"ID\":\"expire-old-tarballs\",\"Status\":\"Enabled\",\"Filter\":{\"Prefix\":\"$NAME/\"},
    \"Expiration\":{\"Days\":$TARBALL_DAYS},\"AbortIncompleteMultipartUpload\":{\"DaysAfterInitiation\":1}}]}" >/dev/null
aws s3api put-bucket-tagging --region "$REGION" --bucket "$BUCKET" \
  --tagging "TagSet=[{Key=Project,Value=$PROJECT},{Key=Name,Value=$BUCKET}]"

# Security group: 80 (certificate challenge, redirect) and 443 (TCP, and UDP for HTTP/3). Never 6379 or 8000.
if none "$SG_ID"; then
  echo "Creating security group $SG_NAME"
  SG_ID=$(ec2 create-security-group --group-name "$SG_NAME" --vpc-id "$VPC" \
    --description "On-call Brain: HTTP and HTTPS only" \
    --tag-specifications "ResourceType=security-group,Tags=[{Key=Name,Value=$SG_NAME},$TAG]" \
    --query GroupId --output text)
fi
open_port() {  # <protocol> <port>: add the rule unless it is there already
  local out
  out=$(ec2 authorize-security-group-ingress --group-id "$SG_ID" \
    --ip-permissions "IpProtocol=$1,FromPort=$2,ToPort=$2,IpRanges=[{CidrIp=0.0.0.0/0}]" \
    --tag-specifications "ResourceType=security-group-rule,Tags=[$TAG]" 2>&1) ||
    [[ $out == *InvalidPermission.Duplicate* ]] || { echo "$out" >&2; return 1; }
}
open_port tcp 80
open_port tcp 443
open_port udp 443

if none "$EIP_ALLOC"; then
  echo "Allocating Elastic IP $EIP_NAME"
  read -r EIP_ALLOC EIP < <(ec2 allocate-address --domain vpc \
    --tag-specifications "ResourceType=elastic-ip,Tags=[{Key=Name,Value=$EIP_NAME},$TAG]" \
    --query '[AllocationId,PublicIp]' --output text)
fi

if none "$INSTANCE"; then
  echo "Launching $BOX ($INSTANCE_TYPE)"
  for try in 1 2 3 4 5 6; do  # a new instance profile takes a few seconds to reach EC2
    if out=$(ec2 run-instances "${RUN_ARGS[@]}" --security-group-ids "$SG_ID" --iam-instance-profile "Name=$ROLE" \
               --query 'Instances[0].InstanceId' --output text 2>&1); then
      INSTANCE=$out
      break
    fi
    if [[ $out != *iamInstanceProfile* ]] || [ "$try" = 6 ]; then echo "$out" >&2; exit 1; fi
    sleep 10
  done
elif [[ $STATE == stop* ]]; then
  echo "Starting $INSTANCE"
  [ "$STATE" = stopping ] && ec2 wait instance-stopped --instance-ids "$INSTANCE"
  ec2 start-instances --instance-ids "$INSTANCE" >/dev/null
fi
echo "Waiting for $INSTANCE to run"
ec2 wait instance-running --instance-ids "$INSTANCE"
if [ "$EIP_INSTANCE" != "$INSTANCE" ]; then
  echo "Associating $EIP with $INSTANCE"
  ec2 associate-address --allocation-id "$EIP_ALLOC" --instance-id "$INSTANCE" >/dev/null
fi

echo
row "instance" "$INSTANCE" ""
row "Elastic IP" "$EIP" ""
row "domain" "${EIP//./-}.sslip.io" ""
echo
echo "Next: deploy/aws/deploy.sh (a new box spends its first 2-3 minutes installing Docker; deploy.sh waits for it)."
