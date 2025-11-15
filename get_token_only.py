from livekit import api
from config import Config

# Generate token
token = (
    api.AccessToken(Config.LIVEKIT_API_KEY, Config.LIVEKIT_API_SECRET)
    .with_identity("customer-" + str(hash(Config.LIVEKIT_API_KEY) % 10000))
    .with_name("Salon Customer")
    .with_grants(api.VideoGrants(
        room_join=True,
        room="salon-calls",
        room_list=True
    ))
).to_jwt()

print("COPY THIS TOKEN:")
print("=" * 50)
print(token)
print("=" * 50)
print("\nThen go to: https://example.livekit.io/")
print("Fill in:")
print("URL: wss://human-in-the-loop-ai-supervisor-u5we6kjz.livekit.cloud")
print("Room: salon-calls") 
print("Token: [paste the token above]")