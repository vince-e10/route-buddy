resource "aws_dynamodb_table" "sessions" {
  name         = var.table_names.sessions
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "session_id"

  attribute {
    name = "session_id"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
}

resource "aws_dynamodb_table" "trips" {
  name         = var.table_names.trips
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "trip_id"

  attribute {
    name = "trip_id"
    type = "S"
  }

  attribute {
    name = "session_id"
    type = "S"
  }

  global_secondary_index {
    name            = "by_session"
    hash_key        = "session_id"
    projection_type = "ALL"
  }
}

resource "aws_dynamodb_table" "action_log" {
  name         = var.table_names.action_log
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "session_id"
  range_key    = "entry_key"

  attribute {
    name = "session_id"
    type = "S"
  }

  attribute {
    name = "entry_key"
    type = "S"
  }
}

resource "aws_dynamodb_table" "pending_actions" {
  name         = var.table_names.pending_actions
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "token"

  attribute {
    name = "token"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
}
