function Header(header)
  if header.level == 1 then
    for _, class_name in ipairs(header.classes) do
      if class_name == "unnumbered" then
        return header
      end
    end
    table.insert(header.classes, "unnumbered")
  end
  return header
end
