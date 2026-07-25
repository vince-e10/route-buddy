variable "table_names" {
  type = object({
    sessions        = string
    trips           = string
    action_log      = string
    pending_actions = string
  })
}
