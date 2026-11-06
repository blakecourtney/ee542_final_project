import zipfile
import io
import fitdecode

def extract_fit(zip_bytes: bytes) -> bytes | None:
    """Return the contents of the .fit file inside Garmin's download ZIP."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        #print(zf.namelist())   # what's inside?
        names = zf.namelist()
        for name in names:
            if name.lower().endswith(".fit"):
                return zf.read(name)
    raise ValueError(f"No .fit file in download (contains: {names})")

if __name__ == "__main__":
    from .api import make_client, download_activity_file
    from .store import save_raw

    activity_id = 24970473464
    client = make_client()

    zip_bytes = download_activity_file(client, activity_id)
    path = save_raw("data", activity_id, zip_bytes)
    fit_bytes = extract_fit(zip_bytes)

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        print(f"ZIP contains: {zf.namelist()}")
    print(f"Saved {path} ({len(zip_bytes):,} bytes)")
    print(f"FIT file: {len(fit_bytes):,} bytes, starts with {fit_bytes[:14]}")

    with fitdecode.FitReader(io.BytesIO(fit_bytes)) as reader:
        counts = {}
        first_record = None
        for frame in reader:
            if frame.frame_type == fitdecode.FIT_FRAME_DATA:
                counts[frame.name] = counts.get(frame.name, 0) + 1
                if frame.name == "record" and first_record is None:
                    first_record = frame
        print(counts)
        for field in first_record.fields:
            print(f"{field.name:30} {field.value!r:30} {field.units}")