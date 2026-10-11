# Going live with your SharePoint — Azure app registration walkthrough

The README lists the four `.env` values. This is the click-by-click for
getting them, in order, plus the pitfalls that actually bite.

## 1. Register the app (about 5 minutes)

1. Go to **portal.azure.com** → search **App registrations** → **New registration**.
2. Name: `proj-manager` (anything you like).
3. Supported account types: **Accounts in this organizational directory only
   (single tenant)**.
4. Redirect URI: **leave blank.** This app uses app-only client-credentials
   auth — there is no interactive sign-in, so no redirect is needed.
5. Click **Register**. On the Overview page, copy two values:
   - **Application (client) ID** → `MS_CLIENT_ID`
   - **Directory (tenant) ID** → `MS_TENANT_ID`

## 2. Grant Graph permissions

1. In the app: **API permissions** → **Add a permission** → **Microsoft Graph**
   → **Application permissions** (not Delegated — this distinction is the
   most common mistake; delegated permissions will not work with this app).
2. Add:
   - `Sites.ReadWrite.All`
   - `Files.ReadWrite.All`

   Why write, when the code today only reads? The shipped code uses Graph
   reads only (resolve site, list libraries, enumerate OneDrive), so
   `Sites.Read.All` + `Files.Read.All` are enough for the connection test.
   But the tool's purpose is migration — the `_copy_item` extension point in
   `backend/app/services.py` writes to the target. Granting ReadWrite now
   saves a second admin-consent round later. If your tenant policy prefers
   least privilege, start with the Read pair and upgrade when the copy loop
   is wired.
3. Click **Grant admin consent for \<tenant\>** and confirm.
   - This step needs a Global Administrator (or Privileged Role Administrator)
     account. If that's not you on this tenant, this is your one real
     blocker: send the admin the app name and the two permissions above —
     everything else you can do yourself.
   - Avoid `Sites.Selected` unless tenant policy forces it: it additionally
     requires a separate per-site permission grant via Graph before anything
     works, which the app does not currently perform.

## 3. Create the client secret

1. **Certificates & secrets** → **New client secret**.
2. Description: `proj-manager local`. Expiry: pick the longest your policy
   allows (24 months if offered) and put the expiry date on your calendar —
   when it lapses, live mode stops until you mint a new secret.
3. Click **Add**, then **copy the Value immediately** → `MS_CLIENT_SECRET`.
   - Pitfall: copy the **Value** column, not the Secret ID. The value is
     shown only once; leave the page and it's gone (fix is just: delete and
     recreate, no harm done).

## 4. Fill `.env` and restart

```
SHAREPOINT_SITE_URL=https://yourtenant.sharepoint.com/sites/YourSite
MS_TENANT_ID=<Directory (tenant) ID>
MS_CLIENT_ID=<Application (client) ID>
MS_CLIENT_SECRET=<secret Value>
ADMIN_TOKEN=<any long random string — gates the Admin tools in the UI>
ONEDRIVE_USER_UPN=<optional; only needed for OneDrive projects, e.g. you@yourtenant.com>
```

```bash
docker compose up --build -d
```

Open http://localhost:8080 — the badge should read **LIVE (Graph)**.
Then **Admin → Test connection**: it resolves your site and lists its
document libraries. If that returns drives, you're live.

## Token lifetime

Graph access tokens expire after roughly an hour. The Graph client tracks
the token's expiry and re-acquires it automatically when it is within
five minutes of lapsing, so live mode runs all day without restarts.
