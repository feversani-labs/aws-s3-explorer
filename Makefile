AWS_PROFILE ?= ephemeral
AWS_SHARED_CREDENTIALS_FILE ?= $(CURDIR)/.aws-credentials
AWS_REGION ?= us-east-1
TF_STATE_PARAMETER ?= /ephemeral-aws-sandbox/tfstate/bucket_name
TF_STATE_KEY ?= $(notdir $(CURDIR))/terraform.tfstate

export AWS_PROFILE AWS_SHARED_CREDENTIALS_FILE AWS_REGION

.PHONY: whoami s3-ls test-post restart-container status-ec2 init plan apply destroy docker-build docker-run

whoami:
	aws sts get-caller-identity

s3-ls:
	aws s3 ls $(BUCKET)

test-post:
	@./scripts/test_post.sh

restart-container:
	@./scripts/restart_container.sh

status-ec2:
	@./scripts/check_ec2.sh

init:
	@bucket="$$(aws ssm get-parameter --name "$(TF_STATE_PARAMETER)" --query 'Parameter.Value' --output text)" && \
	terraform -chdir=terraform init \
		-backend-config="bucket=$$bucket" \
		-backend-config="key=$(TF_STATE_KEY)" \
		-backend-config="region=$(AWS_REGION)"

plan:
	terraform -chdir=terraform plan

apply:
	terraform -chdir=terraform apply

destroy:
	terraform -chdir=terraform destroy

docker-build:
	docker build -t feversani/aws-s3-explorer:latest .

docker-run:
	docker run --rm -it -p 8080:8080 feversani/aws-s3-explorer:latest
