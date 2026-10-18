#!/usr/bin/env bash
# Delete everything deploy/aws/provision.sh and deploy.sh made (docs/DEPLOY.md section E), then run the checks from
# AWS_GUIDE.md section 5 and say what, if anything, is left:
#   deploy/aws/teardown.sh [--yes]
# Asks before deleting; the Parameter Store settings (tokens, the LLM key) get a second question. --yes skips both.
# The graphs go with the box's disk. Back them up first if you want them (docs/DEPLOY.md, "Back up only the graphs").
set -euo pipefail

REGION=ap-south-1
PROJECT=graphhacks
NAME=oncall-brain
SSM_PATH=/graphhacks
ROLE=$NAME-host SG_NAME=$NAME-web EIP_NAME=$NAME-ip BOX=$NAME-box

YES=0
for arg in "$@"; do
  case $arg in
    --yes) YES=1 ;;
    *) echo "usage: $0 [--yes]" >&2; exit 2 ;;
  esac
done

ec2() { aws ec2 "$@" --region "$REGION"; }
iam() { aws iam "$@" --region "$REGION"; }
none() { [ -z "$1" ] || [ "$1" = None ]; }
ask() { [ "$YES" = 1 ] && return; local a; read -rp "$1 [y/N] " a || a=""; [[ $a == [yY]* ]]; }

ACCOUNT=$(aws sts get-caller-identity --region "$REGION" --query Account --output text)
BUCKET=$NAME-$ACCOUNT-$REGION
mine=(--filters "Name=tag:Project,Values=$PROJECT")

find_all() {  # sets the variables below to what still exists (empty when gone)
  INSTANCES=$(ec2 describe-instances "${mine[@]}" "Name=tag:Name,Values=$BOX" \
    Name=instance-state-name,Values=pending,running,stopping,stopped \
    --query 'Reservations[].Instances[].InstanceId' --output text)
  VOLUMES=$(ec2 describe-volumes "${mine[@]}" "Name=tag:Name,Values=$BOX" --query 'Volumes[].VolumeId' --output text)
  read -r EIP_ALLOC EIP < <(ec2 describe-addresses "${mine[@]}" "Name=tag:Name,Values=$EIP_NAME" \
    --query 'Addresses[0].[AllocationId,PublicIp]' --output text)
  none "$EIP_ALLOC" && EIP_ALLOC="" EIP=""
  SG_ID=$(ec2 describe-security-groups "${mine[@]}" "Name=group-name,Values=$SG_NAME" \
    --query 'SecurityGroups[0].GroupId' --output text)
  none "$SG_ID" && SG_ID=""
  PROFILE=$(iam get-instance-profile --instance-profile-name "$ROLE" --query InstanceProfile.InstanceProfileName \
    --output text 2>/dev/null || true)
  ROLE_FOUND=$(iam get-role --role-name "$ROLE" --query Role.RoleName --output text 2>/dev/null || true)
  BUCKET_FOUND=""
  if aws s3api head-bucket --region "$REGION" --bucket "$BUCKET" --expected-bucket-owner "$ACCOUNT" >/dev/null 2>&1
  then BUCKET_FOUND=$BUCKET; fi
  PARAMS=$(aws ssm describe-parameters --region "$REGION" \
    --parameter-filters "Key=Path,Option=Recursive,Values=$SSM_PATH" --query 'Parameters[].Name' --output text)
}
show() { printf '  %-20s %s\n' "$1" "${2:-none}"; }
show_all() {
  show "instance" "$INSTANCES"
  show "Elastic IP" "${EIP:+$EIP ($EIP_ALLOC)}"
  show "security group" "${SG_ID:+$SG_NAME ($SG_ID)}"
  show "IAM role + profile" "${ROLE_FOUND:-$PROFILE}"
  show "S3 bucket" "$BUCKET_FOUND"
  show "SSM parameters" "$PARAMS"
}

find_all
echo "On-call Brain resources in account $ACCOUNT, $REGION:"
show_all
if [ -z "$INSTANCES$EIP$SG_ID$PROFILE$ROLE_FOUND$BUCKET_FOUND$PARAMS" ]; then
  echo "Nothing to delete."
else
  ask "Delete these (the SSM parameters get their own question)?" || { echo "Nothing deleted."; exit 1; }

  if [ -n "$INSTANCES" ]; then
    echo "Terminating $INSTANCES (its disk and graphs go with it)"
    # shellcheck disable=SC2086  # the ids are a space-separated list
    ec2 terminate-instances --instance-ids $INSTANCES >/dev/null
    # shellcheck disable=SC2086
    ec2 wait instance-terminated --instance-ids $INSTANCES
  fi
  if [ -n "$VOLUMES" ]; then
    echo "Waiting for the disk to be deleted"
    # shellcheck disable=SC2086
    ec2 wait volume-deleted --volume-ids $VOLUMES || echo "  $VOLUMES still exists: delete it in EC2 > Volumes"
  fi
  if [ -n "$EIP_ALLOC" ]; then
    echo "Releasing Elastic IP $EIP"
    ec2 release-address --allocation-id "$EIP_ALLOC"
  fi
  if [ -n "$SG_ID" ]; then
    echo "Deleting security group $SG_ID"
    for try in $(seq 12); do  # the terminated box's network interface can take a minute to go
      out=$(ec2 delete-security-group --group-id "$SG_ID" 2>&1) && break
      if [[ $out != *DependencyViolation* ]] || [ "$try" = 12 ]; then echo "$out" >&2; break; fi
      sleep 10
    done
  fi
  if [ -n "$PROFILE" ]; then
    echo "Deleting instance profile $PROFILE"
    for r in $(iam get-instance-profile --instance-profile-name "$PROFILE" \
                 --query 'InstanceProfile.Roles[].RoleName' --output text); do
      iam remove-role-from-instance-profile --instance-profile-name "$PROFILE" --role-name "$r"
    done
    iam delete-instance-profile --instance-profile-name "$PROFILE"
  fi
  if [ -n "$ROLE_FOUND" ]; then
    echo "Deleting IAM role $ROLE"
    for arn in $(iam list-attached-role-policies --role-name "$ROLE" --query 'AttachedPolicies[].PolicyArn' \
                   --output text); do
      iam detach-role-policy --role-name "$ROLE" --policy-arn "$arn"
    done
    for p in $(iam list-role-policies --role-name "$ROLE" --query 'PolicyNames[]' --output text); do
      iam delete-role-policy --role-name "$ROLE" --policy-name "$p"
    done
    iam delete-role --role-name "$ROLE"
  fi
  if [ -n "$BUCKET_FOUND" ]; then
    echo "Emptying and deleting s3://$BUCKET"
    aws s3 rb "s3://$BUCKET" --force --region "$REGION" >/dev/null
  fi
  if [ -n "$PARAMS" ]; then
    if ask "Also delete the settings under $SSM_PATH ($PARAMS)? They are free; a new deploy makes new tokens."; then
      read -ra names <<<"$PARAMS"
      for ((i = 0; i < ${#names[@]}; i += 10)); do  # at most 10 names per call
        aws ssm delete-parameters --region "$REGION" --names "${names[@]:i:10}" >/dev/null
      done
      echo "Deleted $SSM_PATH/*"
    else
      echo "Kept $SSM_PATH/*"
    fi
  fi
fi

# ---- What is left: On-call Brain's own resources, then the region-wide checks from AWS_GUIDE.md section 5 ----------
echo
echo "Left from On-call Brain:"
find_all
show_all
echo "Anything in $REGION that bills (AWS_GUIDE.md section 5):"
billing=0
check() {  # <label> <aws args...>: what the query finds (or the error), else none
  local label=$1 out
  shift
  out=$(aws "$@" --region "$REGION" --output text 2>&1 | tr '\t\n' '  ' | sed 's/ *$//') || true
  show "$label" "$out"
  [ -z "$out" ] || billing=1
}
check "instances" ec2 describe-instances \
  --filters Name=instance-state-name,Values=pending,running,stopping,stopped \
  --query 'Reservations[].Instances[].InstanceId'
check "volumes" ec2 describe-volumes --query 'Volumes[].VolumeId'
check "snapshots" ec2 describe-snapshots --owner-ids self --query 'Snapshots[].SnapshotId'
check "Elastic IPs" ec2 describe-addresses --query 'Addresses[].PublicIp'
check "NAT gateways" ec2 describe-nat-gateways --filter Name=state,Values=available,pending \
  --query 'NatGateways[].NatGatewayId'
check "RDS instances" rds describe-db-instances --query 'DBInstances[].DBInstanceIdentifier'
check "RDS snapshots" rds describe-db-snapshots --query 'DBSnapshots[].DBSnapshotIdentifier'
check "load balancers" elbv2 describe-load-balancers --query 'LoadBalancers[].LoadBalancerName'
echo
if [ -n "$INSTANCES$EIP$SG_ID$PROFILE$ROLE_FOUND$BUCKET_FOUND" ]; then
  echo "Some On-call Brain resources are still there (above). Run this script again, or delete them in the console."
elif [ -n "$PARAMS" ]; then
  echo "Only the free SSM parameters under $SSM_PATH are left."
else
  echo "Nothing from On-call Brain is left."
fi
if [ "$billing" = 1 ]; then
  echo "Something in $REGION still bills (above); it may belong to another project."
else
  echo "Nothing in $REGION bills."
fi
