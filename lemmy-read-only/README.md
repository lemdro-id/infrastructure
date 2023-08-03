The following environment variables are set as secrets in fly.io:
```
LEMMY_DATABASE_URL
```

**NOTE**: This instance's `LEMMY_DATABASE_URL` should point to the read replica(s) of the database! 
Generally, this just means pointing to port `5433` instead of `5432` which always points to a writable member.

It is very important to not just use the default database URL! Instead you will want to use something like 
`top1.nearest.of.lemdroid-lemmy-postgres.internal:5433`

**NOTE**: This instance uses a simplified configuration without support for sending emails or even deleting 
pictrs photos. Read only means read only! Do NOT send requests to this instance without understanding the 
implications of doing so!!
