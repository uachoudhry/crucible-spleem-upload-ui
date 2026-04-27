from crucible import CrucibleClient

client = CrucibleClient()
print(f"API URL: {client.api_url}")
print(f"API key set: {client.api_key is not None}")

# replace with a known email
email = "test@lbl.gov"

result = client.get_user(email=email)
print(f"\nclient.get_user(email='{email}') returned:")
print(result)
