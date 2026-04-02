import httpx

r = httpx.post("http://127.0.0.1:8000/api/v1/dev/login-master")
if r.status_code == 200:
    token = r.json()["access_token"]
    event_id = "ebb7709a-501f-4a8d-b41e-34e6d62707f5" # from latest test output
    headers = {"Authorization": f"Bearer {token}"}
    r_csv = httpx.get(f"http://127.0.0.1:8000/api/v1/events/{event_id}/rooming-list", headers=headers)
    print(r_csv.status_code)
    print(r_csv.text)
else:
    print("Login failed")
