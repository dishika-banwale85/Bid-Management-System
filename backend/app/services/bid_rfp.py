from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile


MAX_RFP_BYTES = 10 * 1024 * 1024
OLE_COMPOUND_SIGNATURE = bytes.fromhex("D0CF11E0A1B11AE1")


def validate_rfp_file(filename: str, raw: bytes) -> tuple[str, str]:
    """Check both the user-facing extension and the file's actual signature."""
    extension = Path(filename).suffix.lower()
    if extension not in {".pdf", ".doc", ".docx"}:
        raise ValueError("Only PDF or Word files up to 10 MB")
    if not raw:
        raise ValueError("The RFP file is empty")
    if len(raw) > MAX_RFP_BYTES:
        raise ValueError("Only PDF or Word files up to 10 MB")

    if extension == ".pdf":
        valid = raw.startswith(b"%PDF-") and b"%%EOF" in raw[-2048:]
        content_type = "application/pdf"
    elif extension == ".doc":
        try:
            import olefile
            if raw.startswith(OLE_COMPOUND_SIGNATURE) and olefile.isOleFile(BytesIO(raw)):
                with olefile.OleFileIO(BytesIO(raw)) as document:
                    streams={"/".join(parts) for parts in document.listdir()}
                    valid="WordDocument" in streams and ("0Table" in streams or "1Table" in streams)
            else:
                valid=False
        except Exception:
            valid=False
        content_type = "application/msword"
    else:
        content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        try:
            with ZipFile(BytesIO(raw)) as archive:
                names = set(archive.namelist())
                valid = "[Content_Types].xml" in names and "word/document.xml" in names
        except (BadZipFile, OSError):
            valid = False

    if not valid:
        raise ValueError("The file contents do not match a valid PDF or Word document")
    return extension, content_type
