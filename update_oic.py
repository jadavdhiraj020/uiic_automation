import sys, re

file_path = 'app/portals/oic/automation/document_upload_module.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

if 'PdfMergeService' not in content:
    content = 'from app.automation.services.pdf_merge_service import PdfMergeService, MergeConfig\n' + content

funcs_to_delete = [
    r'def _get_folder_path\(data: ClaimData\) -> Optional\[str\]:[\s\S]*?(?=def |# ═|$)',
    r'def _collect_remaining_files\([\s\S]*?(?=def |# ═|$)',
    r'def _convert_image_to_pdf_page\([\s\S]*?(?=def |# ═|$)',
    r'def _validate_merged_pdf\([\s\S]*?(?=def |# ═|$)',
    r'def _merge_with_pypdfium2\([\s\S]*?(?=def |# ═|$)',
    r'def _merge_with_pypdf2\([\s\S]*?(?=def |# ═|$)',
    r'def _merge_with_pillow_fallback\([\s\S]*?(?=def |# ═|$)',
    r'def merge_files_to_pdf\([\s\S]*?(?=def |# ═|$)',
    r'def _merge_remaining_to_pdf\([\s\S]*?(?=def |# ═|$)'
]

for pat in funcs_to_delete:
    content = re.sub(pat, '', content)

content = content.replace('_get_folder_path(data)', 'PdfMergeService.get_folder_path(data)')

collect_old = 'remaining = _collect_remaining_files(data, used_files)'
collect_new = '''config = MergeConfig(max_bytes=max_bytes, label="Other Documents", exclude_filenames={"all_pdf_text.txt", "extracted_documents_data.md", "re-inspection report format.pdf", "re-inspection report format.xlsx", "claim_others_documents.pdf", "claim_related_document_merged.pdf", "oic_other_documents_merged.pdf"}, exclude_prefixes={"claim_others_documents_", "oic_other_documents_merged"})
    remaining = PdfMergeService.collect_remaining(data, used_files, config)'''
content = content.replace(collect_old, collect_new)

merge_old = 'merged_path = _merge_remaining_to_pdf(remaining, output_path, log, max_bytes=max_bytes)'
merge_new = 'merged_path = PdfMergeService.merge(remaining, output_path, config, log=log)'
content = content.replace(merge_old, merge_new)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print('Done')
