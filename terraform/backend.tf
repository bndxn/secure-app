terraform {
  backend "s3" {
    bucket         = "ben-secure-app-terraform-state-storage"
    key            = "secure-app/terraform.tfstate"
    region         = "eu-west-1"
    dynamodb_table = "terraform-state-lock"
    encrypt        = true
    profile        = "prod"
  }
}
