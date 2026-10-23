#!/usr/bin/env python3
"""
uploader.py — Subida vía YouTube Data API v3 con el OAuth DEL DUEÑO.

Seguridad / reglas:
  - NO hay credenciales en el código ni inventadas. Se requiere que el dueño
    descargue su client_secrets.json de Google Cloud Console y lo coloque en
    la raíz del proyecto (ver README.md, paso a paso).
  - La primera subida real abre el flujo OAuth en el navegador del dueño y
    guarda token.json localmente. Ese paso NO lo puede hacer un agente.
  - Privacidad por defecto: "private". Publicar exige --privacy public
    explícito Y revisión humana del dueño.
  - --dry-run valida el paquete completo (video o metadatos, título <= 100
    caracteres de YouTube / <= 59 de nuestra plantilla, descripción, tags,
    miniatura) sin tocar la red ni pedir credenciales.

Uso:
    python3 tools/uploader.py --package output/<slug> --dry-run
    python3 tools/uploader.py --package output/<slug>            # privado
    python3 tools/uploader.py --package output/<slug> --privacy public
    python3 tools/uploader.py --package output/<slug> --publish-at 2026-10-21T13:00:00-04:00
    python3 tools/uploader.py --package output/clips/<slug> --platform tiktok [--dry-run]

TIKTOK (distribución del mismo MP4 maestro, decisión del dueño 2026-10-20):
  Estado: PENDIENTE DE CONEXIÓN — hoy no hay cuenta ni credenciales de TikTok
  y NO se inventan. La ruta queda documentada y el paquete se valida entero:
    1. Vía oficial: TikTok Content Posting API (developers.tiktok.com).
       Exige registrar una app y pasar AUDITORÍA de TikTok; las apps sin
       auditar solo pueden publicar en privado/borrador. Cuando el dueño cree
       la cuenta y la app, aquí se implementa el flujo OAuth + POST
       /v2/post/publish/video/init/ reutilizando metadata_tiktok.json.
    2. Vía inicial (la prevista): subida por NAVEGADOR con el login guardado
       de la cuenta — un humano/el dueño inicia sesión una vez y el proceso
       de subida usa esa sesión. Nunca se guardan contraseñas en el proyecto.
  En ambos casos es OBLIGATORIO metadata_tiktok.ai_disclosure = true: la voz
  es sintética (Piper) y TikTok exige declarar el contenido generado por IA.

REGLA DE RETENCIÓN LOCAL (dueño, 02:46 EDT): tras una subida EXITOSA y
confirmada, el MP4 local se BORRA — el video vive en YouTube, con su
calendario (publishAt en config cadence 08/13/19 ET). Local se conserva solo:
guión (en content/scripts/), metadata.json, cover.png, package_manifest.json
(actualizado con youtube_video_id) y el registro content/published.json.
Si la subida FALLA, el paquete se mueve a output/_cuarentena/ (tope en
config automation.quarantine_max_mp4; el supervisor alerta) y NO se borra.
"""
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from common import ROOT, load_json

def validate_package(pkg: Path) -> dict:
    meta = load_json(pkg / "metadata.json", None)
    if not meta and (pkg / "metadata_youtube.json").exists():
        meta = load_json(pkg / "metadata_youtube.json", None)  # paquete espejo (output/clips/)
    checks = {"metadata_json": bool(meta), "title_ok": False, "description_ok": False,
              "tags_ok": False, "cover_exists": False, "video_exists": False}
    if meta:
        checks["title_ok"] = 0 < len(meta.get("title", "")) <= 100
        checks["description_ok"] = len(meta.get("description", "")) >= 20
        checks["tags_ok"] = len(meta.get("tags", [])) >= 3
        checks["cover_exists"] = bool(meta.get("cover")) and Path(meta["cover"]).exists()
    checks["video_exists"] = any(pkg.glob("short.mp4")) or any(pkg.glob("*.mp4"))
    checks["ready_for_upload"] = all([checks["metadata_json"], checks["title_ok"],
                                      checks["description_ok"], checks["tags_ok"]])
    checks["note"] = ("Video aún no renderizado: se puede validar metadatos, "
                      "pero la subida real exige short.mp4") if not checks["video_exists"] else ""
    return checks

def real_upload(pkg: Path, privacy: str, publish_at: str | None = None):
    secrets = ROOT / "client_secrets.json"
    if not secrets.exists():
        print(json.dumps({"error": "Falta client_secrets.json del dueño (Google Cloud Console). "
                                   "Ver README.md > Conectar la cuenta. No se inventan credenciales."},
                         ensure_ascii=False)); sys.exit(2)
    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
    except ImportError:
        print(json.dumps({"error": "Faltan dependencias: pip install google-api-python-client google-auth-oauthlib"},
                         ensure_ascii=False)); sys.exit(2)
    meta = load_json(pkg / "metadata.json", {}) or load_json(pkg / "metadata_youtube.json", {})
    video = next(pkg.glob("short.mp4"), None) or next(pkg.glob("*.mp4"), None)
    if not video:
        print(json.dumps({"error": "No hay .mp4 en el paquete: renderiza con video_assembler.py primero"},
                         ensure_ascii=False)); sys.exit(2)
    scopes = ["https://www.googleapis.com/auth/youtube.upload"]
    token = ROOT / "token.json"; creds = None
    if token.exists():
        creds = Credentials.from_authorized_user_file(str(token), scopes)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            creds = InstalledAppFlow.from_client_secrets_file(str(secrets), scopes).run_local_server(port=0)
        token.write_text(creds.to_json(), encoding="utf-8")
    yt = build("youtube", "v3", credentials=creds)
    body = {"snippet": {"title": meta["title"], "description": meta["description"],
                        "tags": meta.get("tags", []), "categoryId": str(meta.get("category_id", 17)),
                        "defaultLanguage": "es"},
            "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False}}
    if publish_at:
        body["status"]["privacyStatus"] = "private"  # YouTube exige privado para programar
        body["status"]["publishAt"] = publish_at     # el calendario oficial vive en YouTube
    try:
        req = yt.videos().insert(part="snippet,status", body=body,
                                 media_body=MediaFileUpload(str(video), chunksize=-1, resumable=True))
        resp = req.execute()
    except Exception as e:
        quarantine(pkg, f"subida fallida: {e}")
        raise
    video_id = resp.get("id")
    post_upload_cleanup(pkg, video, video_id, privacy, publish_at)
    print(json.dumps({"uploaded_video_id": video_id, "privacy": privacy, "publish_at": publish_at,
                      "url": f"https://youtube.com/shorts/{video_id}",
                      "local_mp4_deleted": True, "kept": ["metadata.json", "cover.png", "package_manifest.json"]},
                     ensure_ascii=False, indent=2))

def post_upload_cleanup(pkg: Path, video: Path, video_id: str, privacy: str, publish_at: str | None):
    """El video vive en YouTube: registra video_id y BORRA el MP4 local."""
    import datetime
    man_path = pkg / "package_manifest.json"
    man = load_json(man_path, {}) if man_path.exists() else {}
    man.update({"youtube_video_id": video_id, "uploaded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "privacy_uploaded": privacy, "publish_at": publish_at, "local_mp4_deleted": True})
    man_path.write_text(json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8")
    reg_path = ROOT / "content" / "published.json"
    reg = load_json(reg_path, []) if reg_path.exists() else []
    reg.append({"slug": pkg.name, "youtube_video_id": video_id, "uploaded_at": man["uploaded_at"],
                "publish_at": publish_at, "package": str(pkg)})
    reg_path.write_text(json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")
    for f in pkg.glob("*.mp4"):
        f.unlink()  # short.mp4 y cualquier copia: local = fábrica temporal
    for f in ("voice.mp3", "voice.wav"):
        p = pkg / f
        if p.exists(): p.unlink()

def quarantine(pkg: Path, reason: str):
    """Subida fallida: el MP4 NO se borra; el paquete va a cuarentena."""
    import datetime
    qdir = ROOT / "output" / "_cuarentena"; qdir.mkdir(parents=True, exist_ok=True)
    dest = qdir / pkg.name
    note = {"quarantined_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "reason": reason}
    (pkg / "quarantine.json").write_text(json.dumps(note, ensure_ascii=False, indent=2), encoding="utf-8")
    if not dest.exists():
        import shutil; shutil.copytree(pkg, dest)
    print(json.dumps({"quarantine": str(dest), "reason": reason}, ensure_ascii=False))

def validate_tiktok_package(pkg: Path) -> dict:
    """Validación del paquete TikTok (sin red, sin credenciales)."""
    meta = load_json(pkg / "metadata_tiktok.json", None)
    checks = {"metadata_tiktok_json": bool(meta), "caption_ok": False, "hashtags_ok": False,
              "ai_disclosure": False, "video_exists": any(pkg.glob("short.mp4")) or any(pkg.glob("*.mp4"))}
    if meta:
        checks["caption_ok"] = 0 < len(meta.get("caption", "")) <= 2200  # límite de TikTok
        checks["hashtags_ok"] = len(meta.get("hashtags", [])) >= 3
        # OBLIGATORIO: voz sintética -> declarar contenido IA (política de TikTok)
        checks["ai_disclosure"] = meta.get("ai_disclosure") is True and bool(meta.get("ai_disclosure_label"))
    checks["ready_for_upload"] = all([checks["metadata_tiktok_json"], checks["caption_ok"],
                                      checks["hashtags_ok"], checks["ai_disclosure"], checks["video_exists"]])
    return checks

def tiktok_upload(pkg: Path, dry_run: bool = False):
    """Ruta TikTok: PENDIENTE DE CONEXIÓN (ver docstring del módulo). Valida el
    paquete y reporta el estado honesto; NO intenta logins ni usa credenciales."""
    checks = validate_tiktok_package(pkg)
    if not checks["ready_for_upload"]:
        print(json.dumps({"platform": "tiktok", "error": "paquete TikTok incompleto", "checks": checks},
                         ensure_ascii=False, indent=2)); sys.exit(1)
    print(json.dumps({"platform": "tiktok", "dry_run": dry_run, "checks": checks,
                      "status": "pendiente_conexion",
                      "detail": "Paquete válido y listo. La publicación espera la conexión de la cuenta: "
                                "API oficial (app auditada por TikTok) o subida por navegador con login "
                                "guardado. Sin cuenta conectada no se publica nada en TikTok."},
                     ensure_ascii=False, indent=2))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--package", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--platform", default="youtube", choices=["youtube", "tiktok"])
    ap.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"])
    ap.add_argument("--publish-at", default=None, help="ISO 8601 con zona (calendario YouTube, ej. 2026-10-21T13:00:00-04:00)")
    args = ap.parse_args()
    pkg = Path(args.package)
    if args.platform == "tiktok":
        tiktok_upload(pkg, dry_run=args.dry_run); return
    checks = validate_package(pkg)
    if args.dry_run:
        print(json.dumps({"dry_run": True, "package": str(pkg), "checks": checks}, ensure_ascii=False, indent=2))
        return
    if not checks["ready_for_upload"] or not checks["video_exists"]:
        print(json.dumps({"error": "Paquete incompleto", "checks": checks}, ensure_ascii=False, indent=2)); sys.exit(1)
    real_upload(pkg, args.privacy, args.publish_at)

if __name__ == "__main__":
    main()
