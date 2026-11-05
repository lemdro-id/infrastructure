#!/bin/bash

# Get the current date and time in the required format
CURRENT_DATE=$(date '+%Y-%m-%d %H:%M:%S.%3N')

# Construct the SQL command
SQL_COMMAND="UPDATE public.\"instance\" SET \"updated\"='$CURRENT_DATE';"

# Execute the SQL command using psql
psql "$LEMMY_DATABASE_URL" -c "$SQL_COMMAND"
