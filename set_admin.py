import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from website import users_db as udb

email = "nexgentutors6@gmail.com"
user = udb.get_user_by_email(email)
if not user:
    print(f"No account found for {email}")
    print("Existing accounts:")
    # Show all profiles so you can pick the right one
    if not udb._USE_SUPABASE:
        with udb._local() as c:
            rows = c.execute("SELECT email, role FROM profiles").fetchall()
            for r in rows:
                print(" ", dict(r))
    sys.exit(1)

print(f"Found: {user['email']} (current role: {user.get('role', 'none')})")
udb.update_profile(user["id"], {"role": "admin"})
updated = udb.get_user(user["id"])
print(f"Updated: {updated['email']} → role={updated.get('role')}")
