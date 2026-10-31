-- Present existing report facts; never synthesize values or conclusions.
-- Work on body blocks only, leaving cover metadata, code and math intact.
local terms = {
  '净资产收益率', '总资产收益率', '净利润率', '毛利率', '净利率',
  '市盈率', '市净率', '股息收益率', '股息率', '资产负债率',
  '经营现金流', '自由现金流', '利息保障倍数', '总资产周转率',
  '每股收益', '净利润', '营业收入', '支撑位', '阻力位', '布林带',
  'ROE', 'ROA', 'EPS', 'P/E', 'P/B', 'PE', 'PB', 'RSI', 'MACD',
  'MA250', 'MA120', 'MA60', 'MA30', 'MA20', 'MA10', 'MA5', 'DCF', 'EBITDA'
}
local units = {'万亿元', '千亿元', '亿元', '万元', '亿股', '万股', '元', '倍', '次', '%', '％'}
local number_pattern = '%d[%d,]*%.?%d*'
local range_separators = {'-', '–', '—', '~', '～', '至'}

local function word_byte(c)
  return c ~= '' and c:match('[A-Za-z0-9_]') ~= nil
end

local function next_match(text, start)
  local best_start, best_end
  local function consider(a, b)
    if a and (not best_start or a < best_start or (a == best_start and b > best_end)) then
      best_start, best_end = a, b
    end
  end
  for _, term in ipairs(terms) do
    local from = start
    while true do
      local a, b = text:find(term, from, true)
      if not a then break end
      local ascii = term:match('^[A-Za-z]') ~= nil
      if not ascii or (not word_byte(text:sub(a - 1, a - 1)) and not word_byte(text:sub(b + 1, b + 1))) then
        consider(a, b)
        break
      end
      from = b + 1
    end
  end
  for _, unit in ipairs(units) do
    local from = start
    while true do
      local a, b = text:find('%d[%d,]*%.?%d*' .. unit:gsub('%%', '%%%%'), from)
      if not a then break end
      -- Do not pick the tail of a decimal or identifier; dates have no units.
      if not word_byte(text:sub(a - 1, a - 1)) and text:sub(a - 1, a - 1) ~= '.' then
        consider(a, b)
        break
      end
      from = b + 1
    end
  end
  for _, separator in ipairs(range_separators) do
    for _, unit in ipairs(units) do
      local pattern = number_pattern .. separator:gsub('([%-])', '%%%1') .. number_pattern .. unit:gsub('%%', '%%%%')
      local a, b = text:find(pattern, start)
      if a and not word_byte(text:sub(a - 1, a - 1)) and text:sub(a - 1, a - 1) ~= '.' then consider(a, b) end
    end
  end
  return best_start, best_end
end

local function spaced_ranges(inlines)
  local out, i = pandoc.List(), 1
  while i <= #inlines do
    local first, j = inlines[i], i + 1
    local number_start = first.t == 'Str' and first.text:find(number_pattern .. '$')
    if number_start and not word_byte(first.text:sub(number_start - 1, number_start - 1)) and first.text:sub(number_start - 1, number_start - 1) ~= '.' then
      if inlines[j] and inlines[j].t == 'Space' then j = j + 1 end
      local separator = inlines[j]
      local is_separator = false
      for _, mark in ipairs(range_separators) do
        if separator and separator.t == 'Str' and separator.text == mark then is_separator = true end
      end
      if is_separator then
        j = j + 1
        if inlines[j] and inlines[j].t == 'Space' then j = j + 1 end
        local last = inlines[j]
        if last and last.t == 'Str' then
          local ending
          for _, unit in ipairs(units) do
            local _, b = last.text:find('^' .. number_pattern .. unit:gsub('%%', '%%%%'))
            if b and (not ending or b > ending) then ending = b end
          end
          if ending then
            local range = pandoc.Inlines({})
            if number_start > 1 then out:insert(pandoc.Str(first.text:sub(1, number_start - 1))) end
            range:insert(pandoc.Str(first.text:sub(number_start)))
            for k = i + 1, j - 1 do range:insert(inlines[k]) end
            range:insert(pandoc.Str(last.text:sub(1, ending)))
            out:insert(pandoc.Strong(range))
            if ending < #last.text then out:insert(pandoc.Str(last.text:sub(ending + 1))) end
            i = j + 1
          else out:insert(first); i = i + 1 end
        else out:insert(first); i = i + 1 end
      else out:insert(first); i = i + 1 end
    else out:insert(first); i = i + 1 end
  end
  return out
end

local function emphasize(str)
  -- A bare URL may be represented as Str rather than Link in old Markdown.
  if str.text:match('^https?://') or str.text:match('^www%.') then return nil end
  local out, cursor = pandoc.List(), 1
  while cursor <= #str.text do
    local a, b = next_match(str.text, cursor)
    if not a then
      out:insert(pandoc.Str(str.text:sub(cursor)))
      break
    end
    if a > cursor then out:insert(pandoc.Str(str.text:sub(cursor, a - 1))) end
    out:insert(pandoc.Strong({pandoc.Str(str.text:sub(a, b))}))
    cursor = b + 1
  end
  return out, false
end

local function labeled_table(list)
  local rows = {}
  for _, item in ipairs(list.content) do
    if #item ~= 1 or (item[1].t ~= 'Plain' and item[1].t ~= 'Para') then return nil end
    local inline = item[1].content
    if #inline < 2 or inline[1].t ~= 'Strong' then return nil end
    local label = pandoc.utils.stringify(inline[1])
    local label_inlines = pandoc.Inlines(inline[1].content)
    local value = pandoc.List()
    for i = 2, #inline do value:insert(inline[i]) end
    while #value > 0 and value[1].t == 'Space' do value:remove(1) end
    local colon = label:match('：$') or label:match(':$')
    if colon then
      local last = label_inlines[#label_inlines]
      -- Retain links, math, code and notes in labels. Only strip a text colon.
      if not last or last.t ~= 'Str' then return nil end
      local text = last.text:sub(1, #last.text - #colon)
      if text == '' then label_inlines:remove(#label_inlines)
      else label_inlines[#label_inlines] = pandoc.Str(text) end
    elseif #value > 0 and value[1].t == 'Str' then
      local text = value[1].text
      local prefix = text:match('^：') or text:match('^:')
      if not prefix then return nil end
      if #text == #prefix then value:remove(1) else value[1] = pandoc.Str(text:sub(#prefix + 1)) end
    else
      return nil
    end
    while #value > 0 and value[1].t == 'Space' do value:remove(1) end
    if #label_inlines == 0 or #value == 0 then return nil end
    rows[#rows + 1] = {
      {pandoc.Plain({pandoc.Strong(label_inlines)})}, {pandoc.Plain(value)}
    }
  end
  if #rows == 0 then return nil end
  return pandoc.utils.from_simple_table(pandoc.SimpleTable(
    {}, {pandoc.AlignLeft, pandoc.AlignLeft}, {0.24, 0.76},
    {{pandoc.Plain({pandoc.Str('观察项')})}, {pandoc.Plain({pandoc.Str('数据与解读')})}}, rows
  ))
end

local function panel(block, environment)
  local result = pandoc.List({pandoc.RawBlock('latex', '\\begin{' .. environment .. '}')})
  -- Use the summary quote as the panel content, rather than nesting two frames.
  if block.t == 'BlockQuote' then result:extend(block.content) else result:insert(block) end
  result:insert(pandoc.RawBlock('latex', '\\end{' .. environment .. '}'))
  return result
end

function Pandoc(doc)
  local blocks, section, summary_done = pandoc.List(), '', false
  local level
  -- The converter removes the report title, but retain headings in standalone use.
  for _, block in ipairs(doc.blocks) do
    if block.t == 'Header' and (not level or block.level < level) then level = block.level end
  end
  for _, block in ipairs(doc.blocks) do
    if block.t == 'Header' and block.level == level then
      section = pandoc.utils.stringify(block)
      summary_done = false
    end
    local is_summary = section:find('摘要', 1, true) ~= nil
    local is_risk = section:find('风险', 1, true) ~= nil
    if is_risk and block.t == 'Header' and block.level == level then
      blocks:insert(pandoc.RawBlock('latex', '\\Needspace{10\\baselineskip}'))
    end
    local is_table_section = section:find('基本面', 1, true) or section:find('估值', 1, true) or section:find('投资建议', 1, true)
    if block.t == 'BulletList' and is_table_section then block = labeled_table(block) or block end
    -- Never put a longtable, figure or raw content inside a breakable frame.
    local summary_safe = block.t == 'Para' or (block.t == 'BlockQuote' and #block.content == 1 and block.content[1].t == 'Para')
    if is_summary and not summary_done and summary_safe then
      blocks:extend(panel(block, 'FinexSummary'))
      summary_done = true
    elseif is_risk and (block.t == 'Para' or block.t == 'BulletList' or block.t == 'OrderedList') then
      local has_table = false
      pandoc.Div({block}):walk({Table = function() has_table = true end})
      if has_table then blocks:insert(block) else blocks:extend(panel(block, 'FinexRisk')) end
    else
      blocks:insert(block)
    end
  end
  doc.blocks = pandoc.Div(blocks):walk({
    traverse = 'topdown',
    Strong = function(el) return el, false end,
    Header = function(el) return el, false end,
    Code = function(el) return el, false end,
    CodeBlock = function(el) return el, false end,
    Math = function(el) return el, false end,
    Inlines = spaced_ranges,
    Str = emphasize
  }).content
  return doc
end
