from __future__ import annotations

import html
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from app.api.auth import dashboard_auth
from app.api.ui import csrf_field, page
from app.services.author_assets import (
    AuthorAssetError,
    author_asset_path,
    canonical_holder_markdown,
    holder_assessments,
    holder_semantics,
    list_author_assets,
    load_author_asset,
    store_author_asset,
)
from app.services.resource_limits import ResourceLimitError

router = APIRouter(dependencies=[Depends(dashboard_auth)])


def _error_response(title: str, message: str, *, status_code: int) -> HTMLResponse:
    response = page(
        title,
        f"""
      <p><a href="/assets">&larr; Back to author asset workspace</a></p>
      <div class="card">
        <h1>{html.escape(title)}</h1>
        <p>{html.escape(message)}</p>
      </div>
    """,
    )
    response.status_code = status_code
    return response


def _asset_cards() -> str:
    records = list_author_assets()
    if not records:
        return '<p class="muted">No uploaded author assets yet.</p>'

    cards: list[str] = []
    for record in records:
        asset_id = str(record["asset_id"])
        href = html.escape(f"/assets/{quote(asset_id, safe='')}", quote=True)
        cards.append(
            f"""
        <div class="card">
          <h3>{html.escape(str(record['original_filename']))}</h3>
          <p class="muted">{int(record['width'])} × {int(record['height'])} px ·
          {html.escape(str(record['format']))} · {int(record['bytes'])} bytes</p>
          <p><a class="button" href="{href}">Inspect and place</a></p>
        </div>
        """
        )
    return "".join(cards)


def _compatibility_table(asset_id: str) -> str:
    rows: list[str] = []
    for result in holder_assessments(asset_id):
        compatible = bool(result["compatible"])
        badge = "Compatible" if compatible else "Not suitable"
        badge_class = "done" if compatible else "failed"
        rows.append(
            f"""
          <tr>
            <td><strong>{html.escape(str(result['holder']))}</strong></td>
            <td><span class="status {badge_class}">{badge}</span></td>
            <td>{float(result['target_width_inches']):g} in</td>
            <td>{float(result['effective_dpi']):.0f} / {int(result['minimum_dpi'])}</td>
            <td>{html.escape(str(result['explanation']))}</td>
          </tr>
        """
        )
    return f"""
      <div style="overflow-x:auto">
        <table style="width:100%; border-collapse:collapse">
          <thead><tr>
            <th style="text-align:left;padding:8px">Holder</th>
            <th style="text-align:left;padding:8px">Source fit</th>
            <th style="text-align:left;padding:8px">Width</th>
            <th style="text-align:left;padding:8px">Effective/min DPI</th>
            <th style="text-align:left;padding:8px">Why</th>
          </tr></thead>
          <tbody>{''.join(rows)}</tbody>
        </table>
      </div>
    """


def _holder_options(selected: str = "inline") -> str:
    options = []
    for value, label in (
        ("inline", "Inline"),
        ("feature", "Feature"),
        ("portrait", "Portrait"),
        ("full-page", "Full page"),
        ("ornament", "Ornament"),
    ):
        selected_attr = " selected" if value == selected else ""
        options.append(f'<option value="{value}"{selected_attr}>{label}</option>')
    return "".join(options)


def _asset_detail(
    asset_id: str,
    *,
    selected_holder: str = "inline",
    alt_text: str = "",
    caption: str = "",
    decorative: bool = False,
    generated_markdown: str = "",
    error: str = "",
) -> HTMLResponse:
    record = load_author_asset(asset_id)
    preview = html.escape(f"/assets/{quote(asset_id, safe='')}/preview", quote=True)
    checked = " checked" if decorative else ""
    generated = ""
    if generated_markdown:
        generated = f"""
      <div class="card">
        <h2>Canonical holder Markdown</h2>
        <p class="muted">Paste this exact line into the manuscript. When the job is queued,
        Book System OS copies the referenced workspace image into the job input tree.</p>
        <textarea readonly style="min-height:100px">{html.escape(generated_markdown)}</textarea>
      </div>
        """
    error_block = (
        f'<div class="card"><h2>Cannot use that selection</h2><p>{html.escape(error)}</p></div>'
        if error
        else ""
    )
    semantics = holder_semantics(selected_holder) if selected_holder in {
        "inline", "feature", "portrait", "full-page", "ornament"
    } else "Choose a named holder to see its controlled layout semantics."

    return page(
        "Author asset",
        f"""
      <p><a href="/assets">&larr; Back to author asset workspace</a></p>
      <div class="card">
        <h1>{html.escape(str(record['original_filename']))}</h1>
        <img src="{preview}" alt="Uploaded asset preview"
             style="display:block;max-width:100%;max-height:520px;width:auto;height:auto;border-radius:10px">
        <p><strong>Source:</strong> {int(record['width'])} × {int(record['height'])} px;
        aspect ratio {float(record['aspect_ratio']):.2f}:1; {html.escape(str(record['format']))};
        {int(record['bytes'])} bytes.</p>
        <p class="muted">Original image bytes are preserved. This workspace does not crop,
        resize or reposition the source.</p>
      </div>

      <div class="card">
        <h2>Holder compatibility</h2>
        <p class="muted">These results come from the same image-holder validator used before export.</p>
        {_compatibility_table(asset_id)}
      </div>

      {error_block}
      <div class="card">
        <h2>Create holder instruction</h2>
        <form method="post" action="/assets/{html.escape(asset_id, quote=True)}/configure">
          {csrf_field()}
          <p><label>Holder<br>
            <select name="holder">{_holder_options(selected_holder)}</select>
          </label></p>
          <p><strong>Layout meaning:</strong> {html.escape(semantics)}</p>
          <p><label>Alt text<br>
            <input name="alt_text" value="{html.escape(alt_text, quote=True)}"
                   placeholder="Describe the image for a reader who cannot see it">
          </label></p>
          <p><label>Caption<br>
            <input name="caption" value="{html.escape(caption, quote=True)}"
                   placeholder="Visible caption when the holder requires or benefits from one">
          </label></p>
          <p><label><input style="width:auto" type="checkbox" name="decorative" value="true"{checked}>
            Decorative image — no informational content</label></p>
          <button type="submit">Generate holder Markdown</button>
        </form>
        <p class="muted">Named holders control layout. Arbitrary coordinates, unrestricted resizing,
        free-floating text and destructive auto-cropping are intentionally unavailable.</p>
      </div>
      {generated}
    """,
    )


@router.get("/assets", response_class=HTMLResponse)
def asset_workspace() -> HTMLResponse:
    return page(
        "Author Asset Workspace",
        f"""
      <p><a href="/">&larr; Back to publishing dashboard</a></p>
      <h1>Author Asset Workspace</h1>
      <p class="muted">Upload an image, inspect whether its source pixels fit each named holder,
      then generate canonical holder Markdown. This is controlled book layout, not a freeform DTP canvas.</p>

      <div class="card">
        <h2>Upload image</h2>
        <form method="post" action="/assets" enctype="multipart/form-data">
          {csrf_field()}
          <p><label>JPEG, PNG or WebP<br><input type="file" name="image" accept="image/jpeg,image/png,image/webp" required></label></p>
          <button type="submit">Upload and inspect</button>
        </form>
      </div>

      <h2>Uploaded assets</h2>
      {_asset_cards()}
    """,
    )


@router.post("/assets")
async def upload_asset(image: UploadFile = File(...)) -> HTMLResponse | RedirectResponse:
    try:
        content = await image.read()
        record = store_author_asset(filename=image.filename, content=content)
    except (AuthorAssetError, ResourceLimitError) as exc:
        status_code = getattr(exc, "status_code", 400)
        return _error_response("Image upload rejected", str(exc), status_code=status_code)
    finally:
        await image.close()

    return RedirectResponse(
        url=f"/assets/{quote(str(record['asset_id']), safe='')}",
        status_code=303,
    )


@router.get("/assets/{asset_id}", response_class=HTMLResponse)
def asset_detail(asset_id: str) -> HTMLResponse:
    try:
        return _asset_detail(asset_id)
    except AuthorAssetError as exc:
        return _error_response("Author asset unavailable", str(exc), status_code=exc.status_code)


@router.post("/assets/{asset_id}/configure", response_class=HTMLResponse)
def configure_asset(
    asset_id: str,
    holder: str = Form(...),
    alt_text: str = Form(""),
    caption: str = Form(""),
    decorative: str = Form(""),
) -> HTMLResponse:
    is_decorative = decorative.strip().lower() in {"1", "true", "yes", "on"}
    try:
        generated = canonical_holder_markdown(
            asset_id,
            holder_name=holder,
            alt_text=alt_text,
            caption=caption,
            decorative=is_decorative,
        )
        return _asset_detail(
            asset_id,
            selected_holder=holder,
            alt_text=alt_text,
            caption=caption,
            decorative=is_decorative,
            generated_markdown=generated,
        )
    except AuthorAssetError as exc:
        try:
            response = _asset_detail(
                asset_id,
                selected_holder=holder,
                alt_text=alt_text,
                caption=caption,
                decorative=is_decorative,
                error=str(exc),
            )
        except AuthorAssetError:
            return _error_response("Author asset unavailable", str(exc), status_code=exc.status_code)
        response.status_code = exc.status_code
        return response


@router.get("/assets/{asset_id}/preview")
def preview_asset(asset_id: str) -> FileResponse | HTMLResponse:
    try:
        record = load_author_asset(asset_id)
        path = author_asset_path(asset_id)
    except AuthorAssetError as exc:
        return _error_response("Author asset unavailable", str(exc), status_code=exc.status_code)

    media_type = {
        "JPEG": "image/jpeg",
        "PNG": "image/png",
        "WEBP": "image/webp",
    }.get(str(record.get("format", "")), "application/octet-stream")
    return FileResponse(path=path, media_type=media_type)
