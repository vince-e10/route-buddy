variable "table_names" {
  type = object({
    sessions        = string
    trips           = string
    action_log      = string
    pending_actions = string
  })
}

variable "point_in_time_recovery_enabled" {
  type    = bool
  default = false
}

variable "deletion_protection_enabled" {
  type    = bool
  default = false
}

variable "server_side_encryption_enabled" {
  type    = bool
  default = false
}
