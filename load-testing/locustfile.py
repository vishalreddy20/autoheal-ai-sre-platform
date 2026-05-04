"""
AutoHeal AI — Locust load testing scenarios.
All users authenticate via /auth/login before running tasks.

Run scenarios:
  Low:    locust -u 10  -r 2  --headless -t 60s  --host http://localhost:8000
  Medium: locust -u 100 -r 10 --headless -t 60s  --host http://localhost:8000
  High:   locust -u 500 -r 50 --headless -t 60s  --host http://localhost:8000
"""
import random
import string

from locust import HttpUser, between, constant_pacing, events, task

# Shared test data
_created_user_ids: list[str] = []
_created_task_ids: list[str] = []


def _random_email() -> str:
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    return f"loadtest_{suffix}@autoheal.test"


def _random_name() -> str:
    return random.choice(["Alice", "Bob", "Carol", "Dave", "Eve", "Frank", "Grace", "Hank"])


def _random_title() -> str:
    verbs = ["Build", "Deploy", "Monitor", "Scale", "Fix", "Review", "Test"]
    nouns = ["pipeline", "dashboard", "service", "alert", "incident", "replica", "report"]
    return f"{random.choice(verbs)} {random.choice(nouns)} #{random.randint(1, 999)}"


class AuthenticatedUser(HttpUser):
    """Base class — logs in as operator before each session."""
    abstract = True

    def on_start(self):
        resp = self.client.post(
            "/auth/login",
            json={"username": "admin", "password": "admin123"},
            name="/auth/login [SETUP]",
        )
        if resp.status_code == 200:
            token = resp.json().get("access_token", "")
            self.client.headers.update({"Authorization": f"Bearer {token}"})
        else:
            raise Exception(f"Login failed: {resp.status_code} {resp.text}")


# ── NormalUser ─────────────────────────────────────────────────────────────────
class NormalUser(AuthenticatedUser):
    wait_time = between(0.5, 2)
    weight = 3

    @task(3)
    def list_users(self):
        page = random.randint(1, 5)
        with self.client.get(
            f"/api/users?page={page}&limit=20",
            catch_response=True,
            name="/api/users [LIST]",
        ) as resp:
            if resp.status_code >= 500:
                resp.failure(f"Server error: {resp.status_code}")

    @task(3)
    def list_tasks(self):
        statuses = ["", "pending", "in_progress", "done", "failed"]
        status = random.choice(statuses)
        url = f"/api/tasks?page=1&limit=20"
        if status:
            url += f"&status={status}"
        with self.client.get(url, catch_response=True, name="/api/tasks [LIST]") as resp:
            if resp.status_code >= 500:
                resp.failure(f"Server error: {resp.status_code}")

    @task(1)
    def create_user(self):
        payload = {"name": _random_name(), "email": _random_email()}
        with self.client.post(
            "/api/users",
            json=payload,
            catch_response=True,
            name="/api/users [CREATE]",
        ) as resp:
            if resp.status_code == 201:
                data = resp.json()
                _created_user_ids.append(data.get("id", ""))
            elif resp.status_code >= 500:
                resp.failure(f"Server error: {resp.status_code}")

    @task(1)
    def create_task(self):
        if not _created_user_ids:
            return
        user_id = random.choice(_created_user_ids)
        payload = {"user_id": user_id, "title": _random_title()}
        with self.client.post(
            "/api/tasks",
            json=payload,
            catch_response=True,
            name="/api/tasks [CREATE]",
        ) as resp:
            if resp.status_code == 201:
                data = resp.json()
                _created_task_ids.append(data.get("id", ""))
            elif resp.status_code >= 500:
                resp.failure(f"Server error: {resp.status_code}")

    @task(2)
    def get_user(self):
        if not _created_user_ids:
            return
        user_id = random.choice(_created_user_ids)
        with self.client.get(
            f"/api/users/{user_id}",
            catch_response=True,
            name="/api/users/{id} [GET]",
        ) as resp:
            if resp.status_code >= 500:
                resp.failure(f"Server error: {resp.status_code}")

    @task(2)
    def get_task(self):
        if not _created_task_ids:
            return
        task_id = random.choice(_created_task_ids)
        with self.client.get(
            f"/api/tasks/{task_id}",
            catch_response=True,
            name="/api/tasks/{id} [GET]",
        ) as resp:
            if resp.status_code >= 500:
                resp.failure(f"Server error: {resp.status_code}")

    @task(1)
    def update_task_status(self):
        if not _created_task_ids:
            return
        task_id = random.choice(_created_task_ids)
        new_status = random.choice(["in_progress", "done", "failed"])
        with self.client.patch(
            f"/api/tasks/{task_id}/status",
            json={"status": new_status},
            catch_response=True,
            name="/api/tasks/{id}/status [PATCH]",
        ) as resp:
            if resp.status_code >= 500:
                resp.failure(f"Server error: {resp.status_code}")

    @task(1)
    def health_check(self):
        with self.client.get("/health", catch_response=True, name="/health") as resp:
            if resp.status_code != 200:
                resp.failure(f"Health check failed: {resp.status_code}")


# ── HeavyUser — spike simulation ──────────────────────────────────────────────
class HeavyUser(AuthenticatedUser):
    wait_time = constant_pacing(0.1)
    weight = 1

    @task(3)
    def list_users(self):
        self.client.get("/api/users?page=1&limit=20", name="/api/users [LIST][SPIKE]")

    @task(2)
    def list_tasks(self):
        self.client.get("/api/tasks?page=1&limit=20", name="/api/tasks [LIST][SPIKE]")

    @task(1)
    def create_user(self):
        payload = {"name": _random_name(), "email": _random_email()}
        resp = self.client.post("/api/users", json=payload, name="/api/users [CREATE][SPIKE]")
        if resp.status_code == 201:
            data = resp.json()
            if data.get("id"):
                _created_user_ids.append(data["id"])

    @task(1)
    def create_task(self):
        if not _created_user_ids:
            return
        user_id = random.choice(_created_user_ids)
        payload = {"user_id": user_id, "title": _random_title()}
        self.client.post("/api/tasks", json=payload, name="/api/tasks [CREATE][SPIKE]")


# ── Event hooks for reporting ──────────────────────────────────────────────────
@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    print(
        "\n[AutoHeal Load Test] Starting — "
        "target: http://api-gateway:8000\n"
    )


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    stats = environment.stats.total
    print(
        f"\n[AutoHeal Load Test] Complete — "
        f"Requests: {stats.num_requests}, "
        f"Failures: {stats.num_failures}, "
        f"Avg RPS: {stats.current_rps:.1f}\n"
    )
