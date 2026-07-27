resource "aws_dynamodb_table" "sessions" {
  name                        = var.table_names.sessions
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "session_id"
  deletion_protection_enabled = var.deletion_protection_enabled

  attribute {
    name = "session_id"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = var.point_in_time_recovery_enabled
  }

  server_side_encryption {
    enabled = var.server_side_encryption_enabled
  }
}

resource "aws_dynamodb_table" "trips" {
  name                        = var.table_names.trips
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "trip_id"
  deletion_protection_enabled = var.deletion_protection_enabled

  attribute {
    name = "trip_id"
    type = "S"
  }

  attribute {
    name = "session_id"
    type = "S"
  }

  global_secondary_index {
    name = "by_session"
    key_schema {
      attribute_name = "session_id"
      key_type       = "HASH"
    }
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = var.point_in_time_recovery_enabled
  }

  server_side_encryption {
    enabled = var.server_side_encryption_enabled
  }
}

resource "aws_dynamodb_table" "action_log" {
  name                        = var.table_names.action_log
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "session_id"
  range_key                   = "entry_key"
  deletion_protection_enabled = var.deletion_protection_enabled

  attribute {
    name = "session_id"
    type = "S"
  }

  attribute {
    name = "entry_key"
    type = "S"
  }

  point_in_time_recovery {
    enabled = var.point_in_time_recovery_enabled
  }

  server_side_encryption {
    enabled = var.server_side_encryption_enabled
  }
}

resource "aws_dynamodb_table" "pending_actions" {
  name                        = var.table_names.pending_actions
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "token"
  deletion_protection_enabled = var.deletion_protection_enabled

  attribute {
    name = "token"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = var.point_in_time_recovery_enabled
  }

  server_side_encryption {
    enabled = var.server_side_encryption_enabled
  }
}
