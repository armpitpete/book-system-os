local HOLDER_WIDTHS = {
  inline = "5.5in",
  feature = "6.25in",
  portrait = "3.5in",
  ["full-page"] = "6.25in",
  ornament = "1in",
}

local CAPTION_REQUIRED = {
  feature = true,
  ["full-page"] = true,
}

local function holder_name(image)
  local primary = image.attributes.holder
  local alias = image.attributes["image-holder"]

  if primary ~= nil and alias ~= nil and primary ~= alias then
    error("conflicting validated image holder metadata reached rendering")
  end

  local holder = primary or alias
  if holder == nil or holder == "" then
    return nil
  end
  if HOLDER_WIDTHS[holder] == nil then
    error("unknown validated image holder reached rendering: " .. holder)
  end
  return holder
end

local function holder_class(holder)
  return "book-system-holder-" .. holder:gsub("[^%w%-]", "-")
end

local function add_class(classes, class_name)
  for _, existing in ipairs(classes) do
    if existing == class_name then
      return
    end
  end
  classes:insert(class_name)
end

local function page_break()
  if FORMAT:match("latex") then
    return pandoc.RawBlock("latex", "\\clearpage")
  end

  if FORMAT == "docx" then
    return pandoc.RawBlock(
      "openxml",
      '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'
    )
  end

  if FORMAT == "epub2" then
    return pandoc.RawBlock(
      "html4",
      '<div class="book-system-page-break" style="page-break-before: always;"></div>'
    )
  end

  if FORMAT:match("epub") or FORMAT:match("html") then
    return pandoc.RawBlock(
      "html5",
      '<div class="book-system-page-break" style="break-before: page; page-break-before: always;"></div>'
    )
  end

  return pandoc.Div(
    {},
    pandoc.Attr(
      "",
      {"book-system-page-break"},
      { ["data-book-system-page-break"] = "true" }
    )
  )
end

function Image(image)
  local holder = holder_name(image)
  if holder == nil then
    return nil
  end

  -- A holder owns geometry. Remove author-supplied format-specific geometry so
  -- the same validated holder cannot drift across writers or bypass the named
  -- placement contract.
  image.attributes.width = HOLDER_WIDTHS[holder]
  image.attributes.height = nil
  image.attributes.style = nil
  image.attributes["latex-placement"] = nil
  image.attributes["data-book-system-holder"] = holder
  add_class(image.classes, holder_class(holder))

  if holder == "ornament" then
    image.attributes.role = "presentation"
    image.attributes["aria-hidden"] = "true"
  end

  return image
end

local function figure_holder_image(figure)
  local found = nil

  pandoc.Div(figure.content):walk({
    Image = function(image)
      local holder = holder_name(image)
      if holder ~= nil then
        if found ~= nil then
          error("multiple holder images in one figure are not supported")
        end
        found = image
      end
      return nil
    end,
  })

  return found
end

local function set_figure_caption(figure, caption_text)
  figure.caption.long = pandoc.read(caption_text, "markdown").blocks
  figure.caption.short = nil
end

function Figure(figure)
  local image = figure_holder_image(figure)
  if image == nil then
    return nil
  end

  local holder = holder_name(image)
  local caption_text = image.attributes.caption
  local has_caption = caption_text ~= nil and caption_text:match("%S") ~= nil

  if CAPTION_REQUIRED[holder] and not has_caption then
    error("image holder '" .. holder .. "' reached rendering without its required caption")
  end

  figure.attributes["data-book-system-holder"] = holder
  add_class(figure.classes, holder_class(holder))

  if has_caption then
    set_figure_caption(figure, caption_text)
  elseif holder == "ornament" then
    -- Decorative ornaments are separators, not captioned figures.
    return figure.content
  else
    -- Pandoc's implicit_figures reader uses image alt text as a visible figure
    -- caption. For optional-caption holders, unwrap that implicit Figure so alt
    -- text remains accessibility text unless the author supplied caption=.
    return figure.content
  end

  if holder == "feature" then
    figure.attributes.style =
      "margin-top: 1.5em; margin-bottom: 1.5em; break-inside: avoid; page-break-inside: avoid;"
  elseif holder == "portrait" then
    figure.attributes.style =
      "margin-top: 1em; margin-bottom: 1em; break-inside: avoid; page-break-inside: avoid;"
  elseif holder == "full-page" then
    figure.attributes.style =
      "margin-top: 0; margin-bottom: 0; break-inside: avoid; page-break-inside: avoid;"
    return {page_break(), figure, page_break()}
  end

  return figure
end
