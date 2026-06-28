# ---------------------------------------------------------------------------
# GitHub Actions OIDC role for pushing platform images to ECR
# ---------------------------------------------------------------------------

resource "aws_iam_openid_connect_provider" "github" {
  count = var.github_actions_oidc_provider_arn == null ? 1 : 0

  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

data "aws_iam_policy_document" "github_actions_assume_role" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.github_oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_actions_repository}:ref:refs/heads/main"]
    }
  }
}

resource "aws_iam_role" "github_actions_ecr" {
  name               = "${var.project_name}-github-actions-ecr"
  assume_role_policy = data.aws_iam_policy_document.github_actions_assume_role.json
}

data "aws_iam_policy_document" "github_actions_ecr_push" {
  statement {
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:CompleteLayerUpload",
      "ecr:DescribeImages",
      "ecr:DescribeRepositories",
      "ecr:GetDownloadUrlForLayer",
      "ecr:InitiateLayerUpload",
      "ecr:PutImage",
      "ecr:UploadLayerPart",
    ]
    resources = [
      aws_ecr_repository.llm_wiki.arn,
      aws_ecr_repository.wiki_ui.arn,
    ]
  }
}

resource "aws_iam_role_policy" "github_actions_ecr_push" {
  name   = "${var.project_name}-ecr-push"
  role   = aws_iam_role.github_actions_ecr.id
  policy = data.aws_iam_policy_document.github_actions_ecr_push.json
}

# ---------------------------------------------------------------------------
# Deploy: GitHub Actions drives an unmanned EC2 deploy via SSM Run Command
# (no inbound SSH). The instance pulls images and reads its own SSM secrets
# under its instance role, so the CI role only needs to send the command and
# read back the invocation result. See .github/workflows/deploy-agent-platform.yml
# and scripts/ec2-deploy.sh (PLA-273).
# ---------------------------------------------------------------------------
data "aws_iam_policy_document" "github_actions_deploy_ssm" {
  statement {
    sid       = "SendCommandToOrigin"
    actions   = ["ssm:SendCommand"]
    resources = [aws_instance.app.arn]
  }

  statement {
    sid       = "SendCommandDocument"
    actions   = ["ssm:SendCommand"]
    resources = ["arn:${data.aws_partition.current.partition}:ssm:${var.aws_region}::document/AWS-RunShellScript"]
  }

  statement {
    sid = "ReadCommandResult"
    actions = [
      "ssm:GetCommandInvocation",
      "ssm:ListCommandInvocations",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "github_actions_deploy_ssm" {
  name   = "${var.project_name}-deploy-ssm"
  role   = aws_iam_role.github_actions_ecr.id
  policy = data.aws_iam_policy_document.github_actions_deploy_ssm.json
}
