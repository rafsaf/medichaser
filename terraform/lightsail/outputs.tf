output "public_ip" {
  value = aws_lightsail_static_ip.this.ip_address
}