# API Versioning and Compatibility Guide

This document defines the API versioning strategy, backwards-compatibility policies, HTTP header standards, and developer procedures for evolving APIs in the **AI Campus Placement Agent** platform (#445).

---

## 1. Overview & Strategy

As the platform evolves with new features—such as enhanced AI evaluations, multi-modal analysis, and institutional integrations—API schemas and routes may change over time. To prevent unexpected breakages in web frontends, mobile clients, or external partner integrations, the platform employs a **URI Path Versioning** strategy complemented by **RFC 8594 Deprecation Headers**.

### Canonical Version Prefix
All current public and authenticated API endpoints are canonically served under:
```
/api/v1/...
```

### Backwards-Compatible Transition Period
To ensure existing client implementations and frontend components continue operating without disruption:
- All legacy unversioned endpoints (`/api/...`) remain fully functional as transparent aliases during the transition window.
- Legacy requests are served with standard RFC 8594 `Deprecation`, `Sunset`, and `Link` headers pointing to their `/api/v1/...` successors.
- No immediate client rewrite is required; clients may migrate on their own schedule before the sunset date.

---

## 2. Active Versions & Lifecycle Status

| Version | URI Prefix | Status | Introduced | Sunset Date | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **v1** | `/api/v1/...` | **Active / Current** | 2026-11 | N/A | Recommended standard for all new clients and integrations. |
| **Legacy** | `/api/...` | **Deprecated** | Initial | **2030-01-01** | Unversioned alias layer maintained for backwards compatibility. |

---

## 3. Standardized HTTP Response Headers

Every API response emitted by the server automatically includes versioning metadata headers to assist client observability, automated routing, and deprecation tracking.

### Versioned (`/api/v1/...`) Responses
When clients call versioned endpoints:
```http
HTTP/1.1 200 OK
Content-Type: application/json
API-Version: v1
X-API-Version: 1.0
X-Request-ID: 7d64fa58-8b9a-4712-b91c-3df6714c7739
```

- **`API-Version`**: The major API version handling the request (`v1`).
- **`X-API-Version`**: Semantic API version number (`1.0`).

### Legacy (`/api/...`) Responses (RFC 8594 Compliant)
When clients call unversioned legacy routes:
```http
HTTP/1.1 200 OK
Content-Type: application/json
API-Version: legacy
Deprecation: true
Sunset: Wed, 01 Jan 2030 00:00:00 GMT
Link: </api/v1/applications>; rel="successor-version"
X-Request-ID: 8a1f2b3c-4d5e-6f7a-8b9c-0d1e2f3a4b5c
```

- **`API-Version`**: Identifies legacy unversioned routing (`legacy`).
- **`Deprecation`**: Signals that the invoked endpoint is deprecated (`true`).
- **`Sunset`**: RFC 8594 timestamp indicating the date after which the unversioned route may be decommissioned (`Wed, 01 Jan 2030 00:00:00 GMT`).
- **`Link`**: RFC 8288 link header with `rel="successor-version"` directing the client to the canonical `/api/v1/...` equivalent.

### Field Deprecation Headers (Input & Payload Deprecation)
When a client sends a request (via JSON body, form data, or query parameters) or receives a response containing deprecated fields, the server automatically injects field deprecation headers alongside RFC 8594 Sunset headers:

```http
HTTP/1.1 200 OK
Content-Type: application/json
API-Version: v1
Deprecation: true
Sunset: Wed, 01 Jan 2030 00:00:00 GMT
Link: </docs/api-versioning>; rel="deprecation"
X-API-Deprecated-Fields: company, role
X-API-Replacement: company -> company_name, role -> target_role
X-API-Removal-Date: 2030-01-01
X-API-Deprecation-Notice: Field 'company' is deprecated and scheduled for removal on 2030-01-01. Please migrate to 'company_name'. Field 'role' is deprecated and scheduled for removal on 2030-01-01. Please migrate to 'target_role'.
```

#### Field Deprecation Header Reference:
- **`Deprecation`**: `true` (RFC 8594 standard).
- **`Sunset`**: `Wed, 01 Jan 2030 00:00:00 GMT` (RFC 8594 / RFC 1123 removal deadline).
- **`Link`**: Link to migration documentation (`rel="deprecation"`).
- **`X-API-Deprecated-Fields`**: Comma-separated list of deprecated fields detected in the request.
- **`X-API-Replacement`**: Direct mapping of deprecated fields to their modern replacements.
- **`X-API-Removal-Date`**: ISO 8601 date (`2030-01-01`) after which the deprecated field will be rejected.
- **`X-API-Deprecation-Notice`**: Human-readable warning and migration instructions for developers.

### Deprecated Fields Catalog

The platform maintains backwards-compatible support for legacy field names while providing direct modern replacements:

| Deprecated Field | Canonical Replacement | Endpoints | Scheduled Removal | Notes |
| :--- | :--- | :--- | :---: | :--- |
| `company` | `company_name` | `/api/v1/analysis/start`, `/api/v1/role-prep/generate` | `2030-01-01` | Use `company_name` for target organization. |
| `role` | `target_role` | `/api/v1/analysis/start`, `/api/v1/role-prep/generate` | `2030-01-01` | Use `target_role` for target job role title. |
| `role_id` | `target_role` | `/api/v1/analysis/start`, `/api/v1/analyze` | `2030-01-01` | Template ID superseded by `target_role`. |
| `selected_role` | `target_role` | `/api/v1/analysis/start`, `/api/v1/analyze` | `2030-01-01` | Use `target_role` for target job role. |
| `input_mode` | `analysis_mode` | `/api/v1/analyze` | `2030-01-01` | Use `analysis_mode` (`upload` or `text`). |
| `cover_letter` | `content` | `/api/v1/cover-letter/download` | `2030-01-01` | Use `content` for cover letter body. |
| `batch_companies`| `companies` | `/api/v1/batch-compare`, `/api/v1/analysis/batch-compare` | `2030-01-01` | Use `companies` array. |
| `resume_analysis_id` | `analysis_id` | `/api/v1/applications`, `/api/v1/applications/create` | `2030-01-01` | Use `analysis_id` to link resume analyses. |
| `notes` | `change_notes` | `/api/v1/analysis/resume/label` | `2030-01-01` | Use `change_notes` for version labels. |
| `tags` | `competencies` | `/api/v1/interview/experience` | `2030-01-01` | Use `competencies` for skill categories. |

---

## 4. Deprecation Metrics and Observability

To help maintainers track real-world deprecated API usage and prioritize sunset timelines, all invocations of deprecated routes and fields are tracked in SQLite table `deprecated_api_metrics`.

### Querying Deprecation Metrics: `GET /api/v1/metrics/deprecation`

Maintainers and observability dashboards can query real-time usage statistics:

```bash
curl -X GET "https://your-domain.com/api/v1/metrics/deprecation?limit=50"
```

#### Sample Response:
```json
{
  "status": "success",
  "total_deprecated_invocations": 42,
  "field_deprecated_invocations": 30,
  "route_deprecated_invocations": 12,
  "fields_summary": [
    {
      "field": "company",
      "replacement": "company_name",
      "removal_date": "2030-01-01",
      "call_count": 18,
      "last_used_at": "2026-11-24 10:15:32"
    },
    {
      "field": "role",
      "replacement": "target_role",
      "removal_date": "2030-01-01",
      "call_count": 12,
      "last_used_at": "2026-11-24 10:15:32"
    }
  ],
  "routes_summary": [
    {
      "route": "/api/analyze",
      "replacement": "/api/v1/analysis/start",
      "removal_date": "2030-01-01",
      "call_count": 12,
      "last_used_at": "2026-11-24 09:40:11"
    }
  ],
  "recent_invocations": [
    {
      "id": "dep-a1b2c3d4e5f6",
      "item_type": "field",
      "item_name": "company",
      "replacement": "company_name",
      "endpoint": "/api/v1/analysis/start",
      "http_method": "POST",
      "user_id": "student_101",
      "timestamp": "2026-11-24 10:15:32"
    }
  ],
  "sunset_date": "2030-01-01",
  "sunset_date_rfc": "Wed, 01 Jan 2030 00:00:00 GMT",
  "migration_guide": "/docs/api-versioning"
}
```

---

## 4. API Version Discovery & Health Endpoints

Clients and integration testing suites can programmatically query active versions and deprecation policies via the discovery endpoint:

### `GET /api/v1/version` (or `GET /api/version`)

#### Response Body:
```json
{
  "status": "success",
  "current_version": "v1",
  "default_version": "v1",
  "supported_versions": ["v1"],
  "deprecated_versions": ["legacy (unversioned /api/...)"],
  "sunset_date": "2030-01-01",
  "sunset_date_rfc": "Wed, 01 Jan 2030 00:00:00 GMT",
  "documentation_url": "/api/v1/docs",
  "openapi_url": "/api/v1/openapi.json",
  "migration_guide": "/docs/api-versioning",
  "policy": {
    "strategy": "URI path prefixing (/api/v1/...) with legacy alias support",
    "backwards_compatibility": "Guaranteed during deprecation transition window",
    "deprecation_header": "Deprecation: true",
    "sunset_header": "Sunset: Wed, 01 Jan 2030 00:00:00 GMT",
    "link_header_rel": "successor-version"
  }
}
```

---

## 5. Interactive Documentation & OpenAPI Specification

Interactive API explorers and raw OpenAPI 3.0.3 specifications are available for both v1 and legacy paths:

| Tool | v1 URL (Canonical) | Legacy URL | Description |
| :--- | :--- | :--- | :--- |
| **Swagger UI** | `/api/v1/docs` | `/docs` or `/api/docs` | Interactive API sandbox for exploring and testing endpoints. |
| **Redoc Reference** | `/api/v1/redoc` | `/redoc` | Clean, 3-column structured API reference. |
| **OpenAPI 3.0.3 Spec** | `/api/v1/openapi.json` | `/api/openapi.json` | Machine-readable OpenAPI JSON specification. |

---

## 6. Client Migration Guide

Migrating existing frontend code or external scripts from `/api/...` to `/api/v1/...` is a zero-risk, drop-in change:

1. **Update the Base URL**:
   Change base URL configurations from:
   ```javascript
   // Legacy
   const API_BASE = "https://your-domain.com/api";
   ```
   to:
   ```javascript
   // Version 1
   const API_BASE = "https://your-domain.com/api/v1";
   ```
2. **Endpoint Parity**:
   All route paths under `/api/v1/...` match the unversioned route structure exactly:
   - `POST /api/analysis/start` &rarr; `POST /api/v1/analysis/start`
   - `GET /api/applications` &rarr; `GET /api/v1/applications`
   - `GET /api/applications/<app_id>` &rarr; `GET /api/v1/applications/<app_id>`
   - `POST /api/interview/evaluate-code` &rarr; `POST /api/v1/interview/evaluate-code`
   - `GET /api/notes` &rarr; `GET /api/v1/notes`
   - `GET /api/health` &rarr; `GET /api/v1/health`
3. **Payloads and Responses**:
   Request bodies, query arguments, session cookies, and response JSON schemas remain 100% identical.

---

## 7. How to Add Future API Versions (e.g. `v2`) Without Breaking Existing Clients

When future changes require breaking API modifications, follow this structured process to introduce a new version safely.

### 7.1. Deciding When a New Version is Needed

| Change Type | Requires New Version (`v2`)? | Action Required |
| :--- | :---: | :--- |
| **Add optional request parameter** | **No** | Add parameter with default fallback in current version. |
| **Add new response field** | **No** | Add field to existing response payload (additive change). |
| **Add new endpoint** | **No** | Add new route to `/api/v1/...`. |
| **Remove or rename an existing field** | **YES** | Create `/api/v2/...`; keep `/api/v1/...` intact. |
| **Change parameter data type** | **YES** | Create `/api/v2/...`; keep `/api/v1/...` intact. |
| **Change HTTP status codes or error structure** | **YES** | Create `/api/v2/...`; keep `/api/v1/...` intact. |
| **Alter endpoint semantics or business logic** | **YES** | Create `/api/v2/...`; keep `/api/v1/...` intact. |

### 7.2. Implementation Steps for `v2`

#### Step 1: Create a Dedicated Blueprint or Module
Create a new version package or blueprint under `utils/api/v2/` or `routes/api_v2.py`:
```python
from flask import Blueprint, jsonify, request

api_v2_bp = Blueprint("api_v2", __name__)

@api_v2_bp.route("/applications", methods=["GET"])
def get_applications_v2():
    # New v2 logic or modified response structure
    return jsonify({
        "version": "2.0",
        "data": [...]
    }), 200
```

#### Step 2: Register the Blueprint with the Versioning Manager
In `app.py` or `utils/api_versioning.py`, register the new version:
```python
from utils.api_versioning import register_api_version
from routes.api_v2 import api_v2_bp

# Registers /api/v2/... and appends 'v2' to SUPPORTED_API_VERSIONS
register_api_version(app, version="v2", blueprint=api_v2_bp, url_prefix="/api/v2")
```

#### Step 3: Inherit Unchanged Handlers
For endpoints that did not change between `v1` and `v2`, you can alias them to the existing handlers or inherit route mappings automatically:
```python
# Alias unchanged v1 endpoints under v2 if desired
app.add_url_rule(
    "/api/v2/health",
    endpoint="api_health_v2",
    view_func=app.view_functions["api_health"]
)
```

#### Step 4: Update the OpenAPI Specification Catalog
Update `utils/openapi_spec.py` to include `/api/v2` in `servers` and document new or modified v2 request/response schemas. Export the updated JSON using:
```bash
python -c "from utils.openapi_spec import export_openapi_json; export_openapi_json()"
```

#### Step 5: Deprecation Lifecycle for the Preceding Version
When `v2` becomes stable:
1. Announce `v1` deprecation in the release notes.
2. Update `utils/api_versioning.py`:
   - Set `CURRENT_API_VERSION = "v2"`
   - Add `v1` to `DEPRECATED_API_VERSIONS`
   - Set the `SUNSET_DATE_RFC` for `v1` (minimum recommended deprecation window: 12 months)
3. The response headers for `/api/v1/...` will automatically begin emitting `Deprecation: true`, `Sunset`, and `Link: </api/v2/...>; rel="successor-version"`.

#### Step 6: Maintain Overlapping Transition Period
Both `v1` and `v2` will run concurrently side-by-side in production, allowing external partners and clients ample time to migrate at their own pace without unexpected outages.

---

## 8. Summary of Architectural Guarantees

1. **Zero Downtime Migrations**: Existing clients calling `/api/...` or `/api/v1/...` will never break when new API versions are introduced.
2. **Explicit Standards Compliance**: Deprecation schedules strictly adhere to RFC 8594 (Sunset header) and RFC 8288 (Link header).
3. **Developer-Friendly Discovery**: Programmatic version querying via `/api/v1/version` and interactive exploration via Swagger UI (`/api/v1/docs`) and Redoc (`/api/v1/redoc`).
