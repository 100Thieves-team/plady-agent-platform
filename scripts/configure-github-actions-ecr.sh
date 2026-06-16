#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TF_DIR="${TF_DIR:-${REPO_ROOT}/infra/terraform/ec2}"
GITHUB_REPO="${GITHUB_REPO:-100Thieves-team/100Thieves-wiki-mcp}"
GH_BIN="${GH_BIN:-/opt/homebrew/bin/gh}"
TERRAFORM_BIN="${TERRAFORM_BIN:-terraform}"
AWS_REGION="${AWS_REGION:-}"
WORKFLOW_FILE="${WORKFLOW_FILE:-docker-images.yml}"
DRY_RUN=false
RUN_WORKFLOW=false

usage() {
  cat <<USAGE
Usage: $0 [options]

Register Terraform ECR outputs as GitHub Actions repository variables.
Run this after 'terraform apply' in infra/terraform/ec2.

Options:
  --tf-dir DIR       Terraform directory. Default: ${TF_DIR}
  --repo OWNER/REPO  GitHub repository. Default: ${GITHUB_REPO}
  --region REGION    AWS region. Default: inferred from terraform output ecr_registry
  --run-workflow     Trigger ${WORKFLOW_FILE} after setting variables
  --dry-run          Print actions without changing GitHub variables
  -h, --help         Show this help

Environment overrides:
  TF_DIR, GITHUB_REPO, GH_BIN, TERRAFORM_BIN, AWS_REGION, WORKFLOW_FILE
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --tf-dir)
      TF_DIR="$2"
      shift 2
      ;;
    --repo)
      GITHUB_REPO="$2"
      shift 2
      ;;
    --region)
      AWS_REGION="$2"
      shift 2
      ;;
    --run-workflow)
      RUN_WORKFLOW=true
      shift
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

require_file() {
  if [ ! -x "$1" ]; then
    echo "Required executable not found: $1" >&2
    echo "Set GH_BIN if your GitHub CLI is installed elsewhere." >&2
    exit 1
  fi
}

terraform_output() {
  local name="$1"
  if ! "$TERRAFORM_BIN" -chdir="$TF_DIR" output -raw "$name" 2>/tmp/llm-wiki-terraform-output.err; then
    cat /tmp/llm-wiki-terraform-output.err >&2
    echo "Failed to read terraform output '${name}'. Did you run terraform apply in ${TF_DIR}?" >&2
    exit 1
  fi
}

set_github_variable() {
  local name="$1"
  local value="$2"

  if [ "$DRY_RUN" = true ]; then
    echo "DRY RUN: ${GH_BIN} variable set ${name} --repo ${GITHUB_REPO} --body ${value}"
  else
    "$GH_BIN" variable set "$name" --repo "$GITHUB_REPO" --body "$value"
  fi
}

command -v "$TERRAFORM_BIN" >/dev/null 2>&1 || {
  echo "Required executable not found in PATH: ${TERRAFORM_BIN}" >&2
  exit 1
}
require_file "$GH_BIN"

ROLE_ARN="$(terraform_output github_actions_ecr_role_arn)"
ECR_REGISTRY="$(terraform_output ecr_registry)"
ECR_LLM_WIKI_REPOSITORY="$(terraform_output ecr_llm_wiki_repository)"
ECR_WIKI_UI_REPOSITORY="$(terraform_output ecr_wiki_ui_repository)"

if [ -z "$AWS_REGION" ]; then
  if [[ "$ECR_REGISTRY" =~ \.dkr\.ecr\.([a-z0-9-]+)\. ]]; then
    AWS_REGION="${BASH_REMATCH[1]}"
  else
    AWS_REGION="ap-northeast-2"
  fi
fi

echo "Configuring GitHub Actions variables for ${GITHUB_REPO}"
echo "Terraform dir: ${TF_DIR}"
echo "AWS region: ${AWS_REGION}"
echo

set_github_variable AWS_ROLE_TO_ASSUME "$ROLE_ARN"
set_github_variable AWS_REGION "$AWS_REGION"
set_github_variable ECR_LLM_WIKI_REPOSITORY "$ECR_LLM_WIKI_REPOSITORY"
set_github_variable ECR_WIKI_UI_REPOSITORY "$ECR_WIKI_UI_REPOSITORY"

if [ "$RUN_WORKFLOW" = true ]; then
  if [ "$DRY_RUN" = true ]; then
    echo "DRY RUN: ${GH_BIN} workflow run ${WORKFLOW_FILE} --repo ${GITHUB_REPO}"
  else
    "$GH_BIN" workflow run "$WORKFLOW_FILE" --repo "$GITHUB_REPO"
  fi
else
  echo
  echo "Variables are ready. To build and push images, run:"
  echo "  ${GH_BIN} workflow run ${WORKFLOW_FILE} --repo ${GITHUB_REPO}"
  echo
  echo "Or rerun this script with --run-workflow."
fi
