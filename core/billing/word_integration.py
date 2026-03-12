from __future__ import annotations

import json
import os
import subprocess
import tempfile


def _run_powershell(script: str, *args: str, timeout_s: int = 120) -> subprocess.CompletedProcess[str]:
    fd, script_path = tempfile.mkstemp(suffix=".ps1", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(script)
        return subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                script_path,
                *[str(a) for a in args],
            ],
            capture_output=True,
            text=True,
            timeout=max(5, int(timeout_s)),
            check=False,
        )
    finally:
        try:
            os.remove(script_path)
        except OSError:
            pass


def word_available() -> tuple[bool, str]:
    script = r"""
param()
$ErrorActionPreference = 'Stop'
$word = $null
try {
  $word = New-Object -ComObject Word.Application
  $word.Visible = $false
  Write-Output "OK"
} finally {
  if ($word -ne $null) {
    $word.Quit()
  }
}
"""
    try:
        res = _run_powershell(script, timeout_s=30)
    except Exception as e:
        return False, str(e)
    if res.returncode == 0 and "OK" in (res.stdout or ""):
        return True, "Microsoft Word automation available."
    return False, (res.stderr or res.stdout or "Microsoft Word automation unavailable.").strip()


def open_docx_in_word(docx_path: str) -> None:
    path = os.path.abspath(str(docx_path))
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    script = r"""
param([string]$SourcePath)
$ErrorActionPreference = 'Stop'
$word = $null
$doc = $null
try {
  $word = New-Object -ComObject Word.Application
  $word.Visible = $true
  $word.Activate()
  $doc = $word.Documents.Open($SourcePath)
  if ($doc -eq $null) {
    throw "Microsoft Word could not open the document: $SourcePath"
  }
  $doc.Activate()
} catch {
  if ($word -ne $null) {
    $word.Quit()
  }
  throw
}
"""
    res = _run_powershell(script, path, timeout_s=30)
    if res.returncode != 0:
        raise RuntimeError((res.stderr or res.stdout or "Could not open DOCX in Microsoft Word.").strip())


def export_docx_to_pdf(docx_path: str, pdf_path: str) -> str:
    source = os.path.abspath(str(docx_path))
    output = os.path.abspath(str(pdf_path))
    if not os.path.exists(source):
        raise FileNotFoundError(source)
    os.makedirs(os.path.dirname(output), exist_ok=True)
    script = r"""
param([string]$SourcePath, [string]$PdfPath)
$ErrorActionPreference = 'Stop'
$wdExportFormatPDF = 17
$word = $null
$doc = $null
try {
  $word = New-Object -ComObject Word.Application
  $word.Visible = $false
  $doc = $word.Documents.Open($SourcePath)
  if ($doc -eq $null) {
    throw "Microsoft Word could not open the document for export: $SourcePath"
  }
  try {
    $doc.Save()
    $doc.ExportAsFixedFormat($PdfPath, $wdExportFormatPDF)
  } finally {
    if ($doc -ne $null) {
      $doc.Close($false)
    }
  }
} finally {
  if ($word -ne $null) {
    $word.Quit()
  }
}
Write-Output $PdfPath
"""
    res = _run_powershell(script, source, output, timeout_s=180)
    if res.returncode != 0:
        raise RuntimeError((res.stderr or res.stdout or "Could not export DOCX to PDF.").strip())
    if not os.path.exists(output):
        raise RuntimeError("Microsoft Word reported success, but the PDF file was not created.")
    return output


def render_word_invoice_template(*, template_path: str, output_path: str, context: dict[str, object]) -> str:
    source = os.path.abspath(str(template_path))
    output = os.path.abspath(str(output_path))
    if not os.path.exists(source):
        raise FileNotFoundError(source)
    os.makedirs(os.path.dirname(output), exist_ok=True)

    fd, context_path = tempfile.mkstemp(suffix=".json", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(context or {}, handle, ensure_ascii=False)

        script = r"""
param([string]$TemplatePath, [string]$OutputPath, [string]$ContextPath)
$ErrorActionPreference = 'Stop'

function Get-CellText([object]$cell) {
  return (($cell.Range.Text -replace "[`r`a]", "")).Trim()
}

function Set-CellText([object]$cell, [string]$text) {
  $range = $cell.Range
  $range.End = $range.End - 1
  $range.Text = $text
}

function Replace-InCell([object]$cell, [string]$oldText, [string]$newText) {
  if ([string]::IsNullOrEmpty($oldText)) {
    return
  }
  $range = $cell.Range
  $range.End = $range.End - 1
  $find = $range.Find
  $find.ClearFormatting()
  $find.Replacement.ClearFormatting()
  [void]$find.Execute($oldText, $false, $false, $false, $false, $false, $true, 1, $false, $newText, 2)
}

function Find-MetadataTable([object]$doc) {
  foreach ($table in $doc.Tables) {
    $allText = ""
    foreach ($row in $table.Rows) {
      foreach ($cell in $row.Cells) {
        $allText += (Get-CellText $cell) + "|"
      }
    }
    if ($allText -match "BILL TO" -and $allText -match "INVOICE #") {
      return $table
    }
  }
  return $null
}

function Find-LineItemsTable([object]$doc) {
  foreach ($table in $doc.Tables) {
    if ($table.Rows.Count -lt 2) {
      continue
    }
    $headerText = ""
    foreach ($cell in $table.Rows.Item(1).Cells) {
      $headerText += ((Get-CellText $cell).ToUpperInvariant()) + "|"
    }
    if ($headerText -match "WORK PERFORMED" -and $headerText -match "AMOUNT") {
      return $table
    }
  }
  return $null
}

function Find-PaymentRowIndex([object]$table) {
  for ($i = 1; $i -le $table.Rows.Count; $i++) {
    foreach ($cell in $table.Rows.Item($i).Cells) {
      if ((Get-CellText $cell).ToUpperInvariant() -match "PAYMENT INSTRUCTIONS") {
        return $i
      }
    }
  }
  return 0
}

function Populate-LineRow([object]$row, [object]$item) {
  if ($row.Cells.Count -ge 1) { Set-CellText $row.Cells.Item(1) "" }
  if ($row.Cells.Count -ge 2) { Set-CellText $row.Cells.Item(2) ([string]$item.work_performed) }
  if ($row.Cells.Count -ge 3) { Set-CellText $row.Cells.Item(3) ([string]$item.itemized_description) }
  if ($row.Cells.Count -ge 4) { Set-CellText $row.Cells.Item(4) ([string]$item.hours_percentage) }
  if ($row.Cells.Count -ge 5) { Set-CellText $row.Cells.Item(5) ([string]$item.rate_per_hour) }
  if ($row.Cells.Count -ge 6) { Set-CellText $row.Cells.Item(6) ([string]$item.amount) }
  if ($row.Cells.Count -ge 7) { Set-CellText $row.Cells.Item(7) "" }
}

$ctx = Get-Content -LiteralPath $ContextPath -Raw | ConvertFrom-Json
Copy-Item -LiteralPath $TemplatePath -Destination $OutputPath -Force

$word = $null
$doc = $null
try {
  $word = New-Object -ComObject Word.Application
  $word.Visible = $false
  $doc = $word.Documents.Open($OutputPath)
  if ($doc -eq $null) {
    throw "Microsoft Word could not open the invoice template: $OutputPath"
  }

  $metaTable = Find-MetadataTable $doc
  if ($metaTable -eq $null) {
    throw "Could not locate the BILL TO / INVOICE metadata table in the master invoice."
  }
  foreach ($row in $metaTable.Rows) {
    foreach ($cell in $row.Cells) {
      Replace-InCell $cell "Dova Health" ([string]$ctx.client_name)
      Replace-InCell $cell "Solveig Johannessen" ([string]$ctx.billing_contact_name)
      Replace-InCell $cell "solveig.johannessen@dovahealth.ca" ([string]$ctx.billing_email)
      Replace-InCell $cell "PM1045" ([string]$ctx.invoice_number)
      Replace-InCell $cell "01/01/26 - 01/31/2026" ([string]$ctx.period_range)
      Replace-InCell $cell "Due upon receipt" ([string]$ctx.due_date)
    }
  }

  $lineTable = Find-LineItemsTable $doc
  if ($lineTable -eq $null) {
    throw "Could not locate the invoice line-items table in the master invoice."
  }

  $paymentRowIndex = Find-PaymentRowIndex $lineTable
  if ($paymentRowIndex -le 0) {
    throw "Could not locate the PAYMENT INSTRUCTIONS row in the invoice line-items table."
  }

  for ($i = $paymentRowIndex - 1; $i -ge 3; $i--) {
    $lineTable.Rows.Item($i).Delete()
  }

  $items = @($ctx.word_line_items)
  if ($items.Count -eq 0) {
    $items = @($ctx.line_items)
  }
  if ($items.Count -eq 0) {
    $items = @(@{
      work_performed = ""
      itemized_description = "(No billable time entries found.)"
      hours_percentage = ""
      rate_per_hour = ""
      amount = ""
    })
  }

  $templateRow = $lineTable.Rows.Item(2)
  Populate-LineRow $templateRow $items[0]

  $paymentRowIndex = Find-PaymentRowIndex $lineTable
  $paymentRow = $lineTable.Rows.Item($paymentRowIndex)
  for ($j = 1; $j -lt $items.Count; $j++) {
    $newRow = $lineTable.Rows.Add($paymentRow)
    $newRow.Range.FormattedText = $templateRow.Range.FormattedText
    Populate-LineRow $newRow $items[$j]
  }

  $paymentRowIndex = Find-PaymentRowIndex $lineTable
  if ($paymentRowIndex -lt $lineTable.Rows.Count) {
    $totalsRow = $lineTable.Rows.Item($paymentRowIndex + 1)
    foreach ($col in 4..6) {
      if ($totalsRow.Cells.Count -ge $col) {
        Set-CellText $totalsRow.Cells.Item($col) ([string]$ctx.total_amount_display)
      }
    }
  }

  $doc.Save()
  Write-Output $OutputPath
} finally {
  if ($doc -ne $null) {
    $doc.Close($true)
  }
  if ($word -ne $null) {
    $word.Quit()
  }
}
"""
        res = _run_powershell(script, source, output, context_path, timeout_s=180)
        if res.returncode != 0:
            raise RuntimeError((res.stderr or res.stdout or "Could not render branded DOCX invoice in Microsoft Word.").strip())
        if not os.path.exists(output):
            raise RuntimeError("Microsoft Word reported success, but the DOCX draft file was not created.")
        return output
    finally:
        try:
            os.remove(context_path)
        except OSError:
            pass
