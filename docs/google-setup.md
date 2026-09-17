# Google Tasks setup

This is the longest part of the install. It is a one-time job. Follow the steps in
order; several of them fail in confusing ways if done out of sequence.

At the end, `wa-inbox` holds an OAuth refresh token in the macOS keychain under the
service name `wa-inbox`, and can create tasks in your own Google Tasks lists.

## 1. Why you need your own OAuth client

You cannot borrow credentials from the `gcloud` CLI. This has been tested and it
does not work.

The `gcloud` CLI cannot grant the Google Tasks scope. Asking it for that scope
fails twice, in this order:

1. The browser shows **This app is blocked**. Google refuses to issue the Tasks
   scope to the `gcloud` client.
2. If you retry non-interactively, the token endpoint returns HTTP 403 with
   `access_denied`.

There is no flag or workaround. Do not spend time on it. You must create your own
Google Cloud project and your own OAuth client. The rest of this document does that.

The token that results belongs to you, stays on your Mac, and is used only to call
`https://tasks.googleapis.com`.

## 2. Create a Google Cloud project

Use the console:

1. Open <https://console.cloud.google.com/projectcreate>.
2. Enter a project name, for example `wa-inbox`.
3. Click **Create**, then wait for the project to be selected.

Or use the CLI, if you already have `gcloud` installed and logged in:

```bash
gcloud projects create wa-inbox-<something-unique> --name="wa-inbox"
gcloud config set project wa-inbox-<something-unique>
```

Project IDs are globally unique, so append something of your own. Note the project
ID down; the next step needs it.

## 3. Enable the Tasks API

CLI:

```bash
gcloud services enable tasks.googleapis.com --project <PROJECT_ID>
```

Console equivalent:

1. Open <https://console.cloud.google.com/apis/library/tasks.googleapis.com>.
2. Check that the project selector at the top shows your project.
3. Click **Enable**.

If the API is not enabled, authorisation still succeeds but every call to the Tasks
API returns an error saying the API has not been used in the project.

## 4. Configure the consent screen

In the current console this section is called **Google Auth Platform**.

1. Open <https://console.cloud.google.com/auth/overview> with your project selected.
2. Click **Get started**.
3. **App name**: `wa-inbox`, or any name. You are the only person who will see it.
4. **User support email**: your own Google address.
5. **Audience**: choose **External**. Internal is only offered on Workspace
   organisations, and it is not what you want for a personal Gmail account.
6. **Contact information**: your own email address again.
7. Accept the Google API Services User Data Policy and click **Create**.

You do not need to add scopes on this screen. The scope is requested by the
`wa-inbox setup-google` command at authorisation time.

## 5. Add yourself as a test user

This is the step everyone skips, and it is the single most common cause of a failed
install.

1. Open <https://console.cloud.google.com/auth/audience> with your project selected.
2. Find the **Test users** section.
3. Click **Add users**.
4. Enter the exact Google address whose Tasks you want `wa-inbox` to write to.
5. Click **Save**.

If you skip this, the browser step in section 7 ends with:

```
Error 403: access_denied
<app name> has not completed the Google verification process.
The app is currently being tested, and can only be accessed by developer-approved testers.
```

The fix is always the same: add that exact address to Test users, then retry. The
address must match the account you pick in the Google account chooser, character for
character. A personal Gmail address and a Workspace address are different users.

## 6. Create the OAuth client

1. Open <https://console.cloud.google.com/auth/clients>.
2. Click **Create client**.
3. **Application type**: **Desktop app**.
4. **Name**: `wa-inbox` (only shown in the console).
5. Click **Create**.
6. In the confirmation dialog, click **Download JSON**.

You get a file named something like `client_secret_1234567890-abcdef.apps.googleusercontent.com.json`.
It is usually in `~/Downloads`.

Do not commit this file to a repository. You can delete it after the next step: its
contents are copied into the keychain.

## 7. Run the setup command

```bash
wa-inbox setup-google ~/Downloads/client_secret_*.json
```

What happens:

1. A browser window opens on Google's account chooser.
2. Pick the account you added as a test user in section 5.
3. You see a screen titled **Google hasn't verified this app**. This is expected.
   The app is yours, it has one user, and Google only verifies apps that are
   distributed publicly.
4. Click **Advanced**, then **Go to wa-inbox (unsafe)**. The word "unsafe" refers to
   unverified third-party apps in general. Here the third party is you.
5. Grant the requested Google Tasks permission.
6. The browser shows a success page and you can close it.

The command then writes the client ID, the client secret and the refresh token into
the macOS keychain, as a single JSON entry under the service name `wa-inbox`. Nothing
is written to a configuration file, and `config.json` never contains a secret.

You can confirm the entry exists without printing it:

```bash
security find-generic-password -s wa-inbox >/dev/null && echo "keychain entry present"
```

## 8. Test mode expires your token after 7 days

Read this section even if everything works. It explains a failure that shows up a
week later.

While the consent screen stays in **Testing**, Google expires refresh tokens after
seven days. Nothing warns you. Task creation simply stops, and the log records an
`invalid_grant` error from the token endpoint.

The fix is to publish the app:

1. Open <https://console.cloud.google.com/auth/audience> with your project selected.
2. In **Publishing status**, click **Publish app**.
3. Confirm the dialog.
4. If Google offers to submit the app for verification, decline it. You do not need
   verification. An unverified app in production is capped at 100 users and cannot
   request sensitive or restricted scopes it has not been granted. The Tasks scope
   works, and 100 users is more than enough for one person.

Publishing does not refresh the token you already have. After publishing, run the
setup once more to obtain a token that does not expire:

```bash
wa-inbox setup-google ~/Downloads/client_secret_*.json
```

You will go through the same browser screens, including the unverified-app warning,
which stays for as long as the app is unverified. The new refresh token replaces the
old one in the keychain.

A token obtained this way lasts until you revoke it, change your Google password in a
way that invalidates sessions, or leave it unused for six months.

## 9. Verify it worked

The quickest check uses the tool's own code and prints your Google Tasks list names:

```bash
python3 -c "from wa_inbox import gtasks; t = gtasks.get_token(); print('\n'.join(gtasks.list_lists(t)))"
```

Run it from the repository root, or from anywhere if `wa-inbox` is installed in the
active environment. Expected output is one list name per line, for example:

```
My Tasks
Inbox
Work
```

If you prefer to see the raw API response:

```bash
TOKEN=$(python3 -c "from wa_inbox import gtasks; print(gtasks.get_token())")
curl -s -H "Authorization: Bearer $TOKEN" \
  https://tasks.googleapis.com/tasks/v1/users/@me/lists
```

Two things to check in the output:

- The list named in `default_list` in your `config.json` (default: `Inbox`) must
  appear. `wa-inbox` refuses to run if that list does not exist, because it is where
  tasks land when the classifier does not pick a list. Google Tasks lists are created
  from the Tasks app or the Google Tasks side panel, not by this tool.
- An error mentioning `invalid_grant` means the refresh token is dead. Go back to
  section 8.

## 10. Revoking access

To remove the credentials from this Mac:

```bash
security delete-generic-password -s wa-inbox
```

That deletes the local copy only. The Google account still trusts the OAuth client.
To cut it off on Google's side:

1. Open <https://myaccount.google.com/permissions>.
2. Find your app under **Third-party apps with account access**.
3. Click it, then **Remove access**.

Doing both leaves nothing behind. You can also delete the Google Cloud project, which
destroys the OAuth client for good.
