module "data" {
  source = "../modules/data"

  table_names = {
    sessions        = "sessions"
    trips           = "trips"
    action_log      = "action_log"
    pending_actions = "pending_actions"
  }
}
