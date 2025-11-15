import typer
import pathlib

from google_auth_oauthlib import flow


_SECRETS_DIR = pathlib.Path(__file__).parent.parent / "secrets"

CLIENT_SECRET_PATH = _SECRETS_DIR / "client_secret.json"
CREDENTIALS_PATH = _SECRETS_DIR / "token.json"

YOTUBE_SCOPES = (
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtubepartner",
    "https://www.googleapis.com/auth/youtube.force-ssl",
)


def run(
    client_secret_path: pathlib.Path = CLIENT_SECRET_PATH,
    credentials_path: pathlib.Path = CREDENTIALS_PATH,
) -> None:
    """Runs Google auth flow

    Args:
        client_secret_path: Path to JSON file with client secret
        credentials_path: Path to JSON file where user token is saved
    """
    installed_app_flow = flow.InstalledAppFlow.from_client_secrets_file(
        client_secrets_file=client_secret_path,
        scopes=YOTUBE_SCOPES,
    )
    creds = installed_app_flow.run_local_server(port=0)

    with open(credentials_path, "w") as token:
        token.write(creds.to_json())


if __name__ == "__main__":
    typer.run(run)
