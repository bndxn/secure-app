.PHONY: help build push deploy terraform-init terraform-plan terraform-apply terraform-destroy test-local

# Variables
AWS_REGION ?= us-east-1
APP_NAME ?= secure-app
ECR_REPO ?= $(shell cd terraform && terraform output -raw ecr_repository_url 2>/dev/null || echo "")

help:
	@echo "Available targets:"
	@echo "  build          - Build Docker image locally"
	@echo "  test-local     - Run the app locally"
	@echo "  push           - Push Docker image to ECR"
	@echo "  deploy         - Full deployment (build, push, terraform apply)"
	@echo "  terraform-init - Initialize Terraform"
	@echo "  terraform-plan - Plan Terraform changes"
	@echo "  terraform-apply - Apply Terraform changes"
	@echo "  terraform-destroy - Destroy Terraform resources"

build:
	docker build -t $(APP_NAME):latest .

test-local:
	docker run -p 8000:8000 -e S3_BUCKET_NAME=test-bucket -e AWS_ACCESS_KEY_ID=dummy -e AWS_SECRET_ACCESS_KEY=dummy $(APP_NAME):latest

terraform-init:
	cd terraform && export AWS_PROFILE=prod && terraform init

terraform-plan:
	cd terraform && export AWS_PROFILE=prod && terraform plan

terraform-apply:
	cd terraform && export AWS_PROFILE=prod && terraform apply

terraform-destroy:
	cd terraform && export AWS_PROFILE=prod && terraform destroy

# Get ECR login and push image
push: build
	@if [ -z "$(ECR_REPO)" ]; then \
		echo "Error: ECR repository URL not found. Run 'terraform apply' first."; \
		exit 1; \
	fi
	aws ecr get-login-password --region $(AWS_REGION) | docker login --username AWS --password-stdin $(ECR_REPO)
	docker tag $(APP_NAME):latest $(ECR_REPO):latest
	docker push $(ECR_REPO):latest

deploy: terraform-init terraform-apply push
	@echo "Deployment complete! Service URL:"
	@cd terraform && terraform output app_runner_service_url
