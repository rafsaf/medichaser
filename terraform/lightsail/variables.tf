variable "aws_region" {
  default = "eu-central-1"
}

variable "availability_zone_suffix" {
  default = "a"
}

variable "name" {
  default = "medichaser"
}

variable "ssh_public_key_path" {
  default = "~/.ssh/id_ed25519.pub"
}

variable "ssh_cidrs" {
  type = list(string)
}