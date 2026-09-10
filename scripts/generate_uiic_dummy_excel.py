"""
generate_uiic_dummy_excel.py
Generates a complete, authentic dummy Excel file for testing the UIIC Portal Automation.
Includes all mandatory and optional fields defined in UIIC field_mapping.json & ClaimData.
"""
import os
import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

def create_uiic_dummy_workbook(output_path: str):
    wb = openpyxl.Workbook()

    # Define color palette & styling
    navy_header_fill = PatternFill(start_color="1A365D", end_color="1A365D", fill_type="solid")
    sub_header_fill  = PatternFill(start_color="2B6CB0", end_color="2B6CB0", fill_type="solid")
    section_fill     = PatternFill(start_color="EBF8FF", end_color="EBF8FF", fill_type="solid")
    zebra_fill       = PatternFill(start_color="F7FAFC", end_color="F7FAFC", fill_type="solid")
    total_fill       = PatternFill(start_color="EDF2F7", end_color="EDF2F7", fill_type="solid")
    highlight_fill   = PatternFill(start_color="FEFCBF", end_color="FEFCBF", fill_type="solid")

    font_title = Font(name="Calibri", size=14, bold=True, color="FFFFFF")
    font_sub_title = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    font_section = Font(name="Calibri", size=11, bold=True, color="2B6CB0")
    font_bold = Font(name="Calibri", size=10, bold=True, color="000000")
    font_normal = Font(name="Calibri", size=10, color="000000")
    font_small = Font(name="Calibri", size=9, italic=True, color="4A5568")

    thin_border_side = Side(border_style="thin", color="CBD5E0")
    thin_border = Border(left=thin_border_side, right=thin_border_side, top=thin_border_side, bottom=thin_border_side)
    thick_bottom = Border(bottom=Side(border_style="medium", color="1A365D"))
    double_bottom = Border(top=thin_border_side, bottom=Side(border_style="double", color="1A365D"))

    # =========================================================================
    # SHEET 1: Survey report
    # =========================================================================
    ws1 = wb.active
    ws1.title = "Survey report"
    ws1.views.sheetView[0].showGridLines = True

    # 1. Letterhead
    ws1["A1"] = "JEEWAN DEEP BATTA"
    ws1["A1"].font = Font(name="Calibri", size=13, bold=True, color="1A365D")
    ws1["F1"] = "17/102, Royal Estate"
    ws1["F1"].font = font_normal

    ws1["A2"] = "Surveyor & Loss Assessor"
    ws1["A2"].font = font_bold
    ws1["F2"] = "Zirakpur, Punjab - 140604"
    ws1["F2"].font = font_normal

    ws1["A3"] = "License No. SLA-7777 Expiry: 26/10/2027"
    ws1["A3"].font = font_normal
    ws1["F3"] = "surveyor_mobile"
    ws1["G3"] = "9814035162"  # Surveyor Mobile
    ws1["F3"].font = font_bold
    ws1["G3"].font = font_normal

    ws1["A4"] = "IISLA Membership: F/N/05949"
    ws1["A4"].font = font_normal
    ws1["I4"] = "jd.batta8810@gmail.com"  # Regex .com email discovery priority cell
    ws1["I4"].font = font_bold
    ws1["H4"] = "surveyor_email"
    ws1["H4"].font = font_bold

    # 2. Document Title Banner
    ws1.merge_cells("A6:I6")
    ws1["A6"] = "MOTOR FINAL SURVEY REPORT (OD CLAIM)"
    ws1["A6"].fill = navy_header_fill
    ws1["A6"].font = font_title
    ws1["A6"].alignment = Alignment(horizontal="center", vertical="center")
    ws1.row_dimensions[6].height = 28

    ws1["A7"] = "The report is issued by me as Licensed surveyor without prejudice in respect of cause, nature & extent of loss/damages and subject to the terms and conditions of Insurance Policy."
    ws1["A7"].font = font_small

    # 3. Report & Invoice Reference Identifiers
    ws1["A9"] = "Ref:"
    ws1["B9"] = "JDB/2026-27/UIIC/8744"  # final_report_no
    ws1["A9"].font = font_bold
    ws1["B9"].font = font_bold

    ws1["C9"] = "Date:"
    ws1["D9"] = "25/04/2026"  # final_report_date / Date:
    ws1["C9"].font = font_bold
    ws1["D9"].font = font_normal

    ws1["E9"] = "Invoice No"
    ws1["F9"] = "INV-2026-0042"  # invoice_no
    ws1["E9"].font = font_bold
    ws1["F9"].font = font_bold

    ws1["G9"] = "Invoice Date"
    ws1["H9"] = "25/04/2026"  # invoice_date
    ws1["G9"].font = font_bold
    ws1["H9"].font = font_normal

    # 4. Insurer & Policy Particulars
    ws1.merge_cells("A11:I11")
    ws1["A11"] = "1. POLICY & CLAIM INFORMATION"
    ws1["A11"].fill = sub_header_fill
    ws1["A11"].font = font_sub_title
    ws1["A11"].alignment = Alignment(horizontal="left", vertical="center", indent=1)

    ws1["A12"] = "INSURERS"
    ws1["B12"] = "United India Insurance Company Limited"
    ws1["A12"].font = font_bold

    ws1["E12"] = "COVER NOTE/POLICY NO."
    ws1["F12"] = "1103003122P113572944"
    ws1["E12"].font = font_bold

    ws1["A13"] = "Claim Number"
    ws1["B13"] = "2230003126C065430001"  # claim_no (mandatory)
    ws1["A13"].font = font_bold
    ws1["B13"].font = font_bold
    ws1["B13"].fill = highlight_fill

    ws1["E13"] = "Period of Insurance"
    ws1["F13"] = "29-Mar-2024 to 28-Mar-2025"
    ws1["E13"].font = font_bold

    ws1["A14"] = "Type of Settlement"
    ws1["B14"] = "Partial Loss"  # type_of_settlement
    ws1["A14"].font = font_bold

    ws1["E14"] = "IDV (Rs.)"
    ws1["F14"] = "8,50,000"
    ws1["E14"].font = font_bold

    # 5. Insured & Vehicle Details
    ws1.merge_cells("A16:I16")
    ws1["A16"] = "2. INSURED & VEHICLE PARTICULARS"
    ws1["A16"].fill = sub_header_fill
    ws1["A16"].font = font_sub_title
    ws1["A16"].alignment = Alignment(horizontal="left", vertical="center", indent=1)

    ws1["A17"] = "INSURED NAME"
    ws1["B17"] = "AJAY SINGH"
    ws1["A17"].font = font_bold

    ws1["E17"] = "REGISTRATION NO."
    ws1["F17"] = "DL-3S-EK-1646"
    ws1["E17"].font = font_bold

    ws1["A18"] = "INSURED ADDRESS"
    ws1["B18"] = "B-27 Jagatpuri, Krishna Nagar, East Delhi 110051"
    ws1["A18"].font = font_bold

    ws1["E18"] = "MAKE & MODEL"
    ws1["F18"] = "Kawasaki Ninja ZX-10R"
    ws1["E18"].font = font_bold

    ws1["A19"] = "Mobile:"
    ws1["B19"] = "9814035162"  # mobile_no
    ws1["A19"].font = font_bold

    ws1["E19"] = "CHASSIS / ENGINE NO."
    ws1["F19"] = "JKAZX1000FFA12345 / ZX1000EE012345"
    ws1["E19"].font = font_bold

    ws1["A20"] = "Odometer Reading"
    ws1["B20"] = "45230"  # odometer
    ws1["A20"].font = font_bold

    ws1["E20"] = "Nil Depreciation"
    ws1["F20"] = "Yes"  # nil_depreciation
    ws1["E20"].font = font_bold
    ws1["F20"].font = font_bold

    # 6. Survey Details & Place
    ws1.merge_cells("A22:I22")
    ws1["A22"] = "3. SURVEY PARTICULARS"
    ws1["A22"].fill = sub_header_fill
    ws1["A22"].font = font_sub_title
    ws1["A22"].alignment = Alignment(horizontal="left", vertical="center", indent=1)

    ws1["A23"] = "Date and Time of Survey"
    ws1["E23"] = "20/04/2026 11:30 AM"  # date_of_survey + survey time (col_offset: 4)
    ws1["F23"] = "11:30 AM"             # Adjacent cell survey time
    ws1["A23"].font = font_bold
    ws1["E23"].font = font_bold
    ws1["E23"].fill = highlight_fill

    ws1["A24"] = "Place of survey"
    ws1["E24"] = "Authorized Service Workshop, Okhla Industrial Area Phase 3, New Delhi" # place_of_survey (col_offset: 4)
    ws1["A24"].font = font_bold
    ws1["E24"].font = font_normal

    ws1["A25"] = "Initial Loss Assessment"
    ws1["B25"] = "100000"  # initial_loss_amount (UIIC applies 75% -> 75,000)
    ws1["A25"].font = font_bold
    ws1["B25"].font = font_bold
    ws1["B25"].fill = highlight_fill

    ws1["E25"] = "Expected Completion Date"
    ws1["F25"] = "20/05/2026"  # Expected completion date (+1 month)
    ws1["E25"].font = font_bold

    # 7. Parts Assessment Table
    ws1.merge_cells("A27:I27")
    ws1["A27"] = "4. CLAIM ASSESSMENT — PARTS REPLACED"
    ws1["A27"].fill = sub_header_fill
    ws1["A27"].font = font_sub_title
    ws1["A27"].alignment = Alignment(horizontal="left", vertical="center", indent=1)

    parts_headers = [
        "S.N.", "PART DESCRIPTION", "ESTIMATE (Rs.)", "ASSESSED (Rs.)",
        "QTY", "AGE DEP (Rs.)", "50% DEP (Rs.)", "NIL DEP (Rs.)", "GST 18% (Rs.)"
    ]
    for c_idx, h_text in enumerate(parts_headers, start=1):
        cell = ws1.cell(row=28, column=c_idx, value=h_text)
        cell.font = font_bold
        cell.fill = section_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border

    parts_rows = [
        (1, "Cowling, Upper Fairing Front", 12500, 11000, 1, 3500, 0, 0, 1350),
        (2, "Headlight Assembly Headlamp", 18500, 16000, 1, 5500, 0, 0, 1890),
        (3, "Fairing Bracket & Stays", 4500, 4000, 1, 0, 2000, 0, 360),
        (4, "Front Mudguard Fender (Plastic)", 5000, 5000, 1, 0, 2500, 0, 450),
        (5, "Fuel Tank Outer Cover", 9000, 8000, 1, 6000, 0, 0, 360),
        (6, "Brake Lever & Master Cylinder", 6000, 6000, 1, 0, 0, 6000, 1080),
    ]

    for r_offset, p_data in enumerate(parts_rows, start=29):
        for col_i, val in enumerate(p_data, start=1):
            cell = ws1.cell(row=r_offset, column=col_i, value=val)
            cell.font = font_normal
            cell.border = thin_border
            if col_i in (3, 4, 6, 7, 8, 9):
                cell.number_format = "#,##0.00"
                cell.alignment = Alignment(horizontal="right")
            elif col_i in (1, 5):
                cell.alignment = Alignment(horizontal="center")

    # SUB TOTAL Row for Parts (Config requires: SUB TOTAL with col_offset 5=Age, 6=50%, 7=Nil, 8=GST 18%)
    # Row 35: Column A=SUB TOTAL, B=blank, C=blank, D=blank, E=blank, F=AgeDep, G=50%Dep, H=NilDep, I=GST18
    r_sub = 35
    ws1.cell(row=r_sub, column=1, value="SUB TOTAL").font = font_bold
    ws1.cell(row=r_sub, column=1).fill = total_fill
    ws1.cell(row=r_sub, column=1).border = thin_border

    ws1.cell(row=r_sub, column=4, value=50000.0).number_format = "#,##0.00"  # Total assessed parts
    ws1.cell(row=r_sub, column=4).font = font_bold
    ws1.cell(row=r_sub, column=4).border = thin_border

    ws1.cell(row=r_sub, column=6, value=15000.0).number_format = "#,##0.00"  # col_offset 5: parts_age_dep_excl_gst
    ws1.cell(row=r_sub, column=6).font = font_bold
    ws1.cell(row=r_sub, column=6).fill = highlight_fill
    ws1.cell(row=r_sub, column=6).border = thin_border

    ws1.cell(row=r_sub, column=7, value=4500.0).number_format = "#,##0.00"   # col_offset 6: parts_50_dep_excl_gst
    ws1.cell(row=r_sub, column=7).font = font_bold
    ws1.cell(row=r_sub, column=7).fill = highlight_fill
    ws1.cell(row=r_sub, column=7).border = thin_border

    ws1.cell(row=r_sub, column=8, value=6000.0).number_format = "#,##0.00"   # col_offset 7: parts_nil_dep_excl_gst
    ws1.cell(row=r_sub, column=8).font = font_bold
    ws1.cell(row=r_sub, column=8).fill = highlight_fill
    ws1.cell(row=r_sub, column=8).border = thin_border

    ws1.cell(row=r_sub, column=9, value=4590.0).number_format = "#,##0.00"   # col_offset 8: parts_gst18_amount
    ws1.cell(row=r_sub, column=9).font = font_bold
    ws1.cell(row=r_sub, column=9).fill = highlight_fill
    ws1.cell(row=r_sub, column=9).border = thin_border

    # 8. GST Summary - Spares (row_offset 4, col_offset 1 from 'GST SUMMARY - SPARES')
    ws1["A37"] = "GST SUMMARY - SPARES"
    ws1["A37"].font = font_bold

    ws1["A38"] = "Rate %"
    ws1["B38"] = "Taxable Amount"
    ws1["C38"] = "CGST 9%"
    ws1["D38"] = "SGST 9%"
    ws1["E38"] = "Total GST"
    for c in ["A38", "B38", "C38", "D38", "E38"]:
        ws1[c].font = font_bold
        ws1[c].fill = section_fill
        ws1[c].border = thin_border

    ws1["A39"] = "18%"
    ws1["B39"] = 25500.0
    ws1["C39"] = 2295.0
    ws1["D39"] = 2295.0
    ws1["E39"] = 4590.0
    for c in ["A39", "B39", "C39", "D39", "E39"]:
        ws1[c].font = font_normal
        ws1[c].border = thin_border

    ws1["A40"] = "Others"
    ws1["B40"] = 0.0
    ws1["C40"] = 0.0
    ws1["D40"] = 0.0
    ws1["E40"] = 0.0
    for c in ["A40", "B40", "C40", "D40", "E40"]:
        ws1[c].font = font_normal
        ws1[c].border = thin_border

    # Row 41 is row 37 + 4 -> col B is col A + 1: gst_summary_parts = 25500
    ws1["A41"] = "Total"
    ws1["B41"] = 25500.0  # gst_summary_parts
    ws1["C41"] = 2295.0
    ws1["D41"] = 2295.0
    ws1["E41"] = 4590.0
    for c in ["A41", "B41", "C41", "D41", "E41"]:
        ws1[c].font = font_bold
        ws1[c].fill = highlight_fill if c == "B41" else total_fill
        ws1[c].border = double_bottom

    # 9. Labour Charges Table
    ws1.merge_cells("A43:I43")
    ws1["A43"] = "5. CLAIM ASSESSMENT — LABOUR CHARGES"
    ws1["A43"].fill = sub_header_fill
    ws1["A43"].font = font_sub_title
    ws1["A43"].alignment = Alignment(horizontal="left", vertical="center", indent=1)

    labour_headers = ["S.N.", "LABOUR WORK DESCRIPTION", "ESTIMATE (Rs.)", "R/R (Rs.)", "DENTING (Rs.)", "PAINTING (Rs.)", "TOTAL (Rs.)"]
    for c_idx, h_text in enumerate(labour_headers, start=1):
        cell = ws1.cell(row=44, column=c_idx, value=h_text)
        cell.font = font_bold
        cell.fill = section_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border

    labour_rows = [
        (1, "R/R Cowling, Headlamp, Fairing, Tank", 4500, 3500, 0, 0, 3500),
        (2, "Denting & Alignment of brackets & stays", 3500, 0, 2500, 0, 2500),
        (3, "Painting of Cowling Upper & Tank Cover", 8000, 0, 0, 6000, 6000),
    ]
    for r_offset, l_data in enumerate(labour_rows, start=45):
        for col_i, val in enumerate(l_data, start=1):
            cell = ws1.cell(row=r_offset, column=col_i, value=val)
            cell.font = font_normal
            cell.border = thin_border
            if col_i in (3, 4, 5, 6, 7):
                cell.number_format = "#,##0.00"
                cell.alignment = Alignment(horizontal="right")
            elif col_i == 1:
                cell.alignment = Alignment(horizontal="center")

    # Labour Total Row: TOTAL (R/R, DENTING, C/W, PAINTING)
    ws1["A48"] = "TOTAL (R/R, DENTING, C/W, PAINTING)"
    ws1["B48"] = 12000.0  # labour_excl_gst (mandatory)
    ws1["A48"].font = font_bold
    ws1["B48"].font = font_bold
    ws1["B48"].fill = highlight_fill
    ws1["B48"].number_format = "#,##0.00"

    # 10. GST Summary - Labour (row_offset 4, col_offset 1 from 'GST SUMMARY - LABOUR')
    ws1["A50"] = "GST SUMMARY - LABOUR"
    ws1["A50"].font = font_bold

    ws1["A51"] = "Rate %"
    ws1["B51"] = "Taxable Amount"
    ws1["C51"] = "CGST 9%"
    ws1["D51"] = "SGST 9%"
    ws1["E51"] = "Total Amount"
    for c in ["A51", "B51", "C51", "D51", "E51"]:
        ws1[c].font = font_bold
        ws1[c].fill = section_fill
        ws1[c].border = thin_border

    ws1["A52"] = "18%"
    ws1["B52"] = 12000.0
    ws1["C52"] = 1080.0
    ws1["D52"] = 1080.0
    ws1["E52"] = 14160.0
    for c in ["A52", "B52", "C52", "D52", "E52"]:
        ws1[c].font = font_normal
        ws1[c].border = thin_border

    ws1["A53"] = "Others"
    ws1["B53"] = 0.0
    ws1["C53"] = 0.0
    ws1["D53"] = 0.0
    ws1["E53"] = 0.0
    for c in ["A53", "B53", "C53", "D53", "E53"]:
        ws1[c].font = font_normal
        ws1[c].border = thin_border

    # Row 54 is row 50 + 4 -> col B is col A + 1: gst_summary_labour = 12000
    ws1["A54"] = "Total"
    ws1["B54"] = 12000.0  # gst_summary_labour
    ws1["C54"] = 1080.0
    ws1["D54"] = 1080.0
    ws1["E54"] = 14160.0
    for c in ["A54", "B54", "C54", "D54", "E54"]:
        ws1[c].font = font_bold
        ws1[c].fill = highlight_fill if c == "B54" else total_fill
        ws1[c].border = double_bottom

    # 11. Other Charges & Deductions
    ws1.merge_cells("A56:I56")
    ws1["A56"] = "6. OTHER CHARGES & POLICY DEDUCTIONS"
    ws1["A56"].fill = sub_header_fill
    ws1["A56"].font = font_sub_title
    ws1["A56"].alignment = Alignment(horizontal="left", vertical="center", indent=1)

    # Row 57: Towing charges (col_offset 4 and 1)
    ws1["A57"] = "TOWING CHARGES"
    ws1["B57"] = 1500.0  # towing_charges
    ws1["E57"] = 1500.0  # col_offset 4 hint
    ws1["A57"].font = font_bold
    ws1["B57"].font = font_normal
    ws1["E57"].font = font_normal

    # Row 58: Voluntary excess (col_offset 5 and 1)
    ws1["A58"] = "voluntry excess"
    ws1["B58"] = 0.0  # voluntary_excess
    ws1["F58"] = 0.0  # col_offset 5 hint
    ws1["A58"].font = font_bold
    ws1["B58"].font = font_normal

    # Row 59: Compulsory excess (col_offset 1)
    ws1["A59"] = "Less Compulsory Excess"
    ws1["B59"] = 1000.0  # compulsory_excess
    ws1["A59"].font = font_bold
    ws1["B59"].font = font_bold
    ws1["B59"].fill = highlight_fill

    # Row 60: Imposed excess (col_offset 5 and 1)
    ws1["A60"] = "Less Imposed Excess"
    ws1["B60"] = 0.0  # imposed_excess
    ws1["F60"] = 0.0  # col_offset 5 hint
    ws1["A60"].font = font_bold
    ws1["B60"].font = font_normal

    # Row 61: Salvage value (col_offset 5 and 1)
    ws1["A61"] = "LESS SALVAGE VALUE"
    ws1["B61"] = 1200.0  # salvage_value
    ws1["F61"] = 1200.0  # col_offset 5 hint
    ws1["A61"].font = font_bold
    ws1["B61"].font = font_bold

    # Row 62: Spot repairs
    ws1["A62"] = "Spot Repairs"
    ws1["B62"] = 0.0
    ws1["A62"].font = font_bold

    # 12. Settlement Recommendation & Surveyor Observations
    ws1.merge_cells("A64:I64")
    ws1["A64"] = "7. SETTLEMENT RECOMMENDATION & OBSERVATIONS"
    ws1["A64"].fill = sub_header_fill
    ws1["A64"].font = font_sub_title
    ws1["A64"].alignment = Alignment(horizontal="left", vertical="center", indent=1)

    # Row 65: Payment in favour of REPAIRER -> triggers Cashless settlement
    ws1["A65"] = "The payment to be made in favour of"
    ws1["B65"] = "REPAIRER"  # payment_to (Cashless)
    ws1["A65"].font = font_bold
    ws1["B65"].font = font_bold
    ws1["B65"].fill = highlight_fill

    # Row 67: Surveyor Observations
    ws1["A67"] = "OBERVATIONS/COMMENTS"
    ws1["A67"].font = font_bold
    ws1["A68"] = "Vehicle inspected thoroughly at the repairer workshop. All claimed damages correlate with the narrated cause of accident. Parts replacement and labour assessment have been verified strictly as per policy norms and market rates. Claim is recommended for settlement on Cashless basis."
    ws1["A68"].font = font_normal
    ws1.merge_cells("A68:I68")

    # 13. Surveyor Charges Summary on Report
    ws1.merge_cells("A70:I70")
    ws1["A70"] = "8. SURVEYOR CHARGES SUMMARY"
    ws1["A70"].fill = sub_header_fill
    ws1["A70"].font = font_sub_title
    ws1["A70"].alignment = Alignment(horizontal="left", vertical="center", indent=1)

    ws1["A71"] = "SURVEY FEE"
    ws1["B71"] = 2500.0  # survey_fee
    ws1["F71"] = 2500.0  # col_offset 5
    ws1["A71"].font = font_bold
    ws1["B71"].font = font_normal

    ws1["A72"] = "REINSPECTION FEE"
    ws1["B72"] = 750.0   # reinspection_fee
    ws1["F72"] = 750.0   # col_offset 5
    ws1["A72"].font = font_bold
    ws1["B72"].font = font_normal

    ws1["A73"] = "CONVEYANCE CHARGES"
    ws1["B73"] = 500.0   # traveling_expenses
    ws1["F73"] = 500.0   # col_offset 5
    ws1["A73"].font = font_bold
    ws1["B73"].font = font_normal

    ws1["A74"] = "DAILY ALLOWANCE"
    ws1["B74"] = 250.0   # daily_allowance
    ws1["F74"] = 250.0   # col_offset 5
    ws1["A74"].font = font_bold
    ws1["B74"].font = font_normal

    ws1["A75"] = "PHOTOGRAPHS"
    ws1["B75"] = 300.0   # photo_charges
    ws1["F75"] = 300.0   # col_offset 5
    ws1["A75"].font = font_bold
    ws1["B75"].font = font_normal

    # Auto-adjust column widths for Sheet 1
    col_widths = {
        "A": 34, "B": 28, "C": 18, "D": 20,
        "E": 26, "F": 22, "G": 18, "H": 18, "I": 24
    }
    for col_letter, width in col_widths.items():
        ws1.column_dimensions[col_letter].width = width

    # =========================================================================
    # SHEET 2: Survey fee Bill
    # =========================================================================
    ws2 = wb.create_sheet(title="Survey fee Bill")
    ws2.views.sheetView[0].showGridLines = True

    # 1. Letterhead
    ws2["A1"] = "JEEWAN DEEP BATTA"
    ws2["A1"].font = Font(name="Calibri", size=13, bold=True, color="1A365D")
    ws2["F1"] = "17/102, Royal Estate"
    ws2["F1"].font = font_normal

    ws2["A2"] = "Surveyor & Loss Assessor"
    ws2["A2"].font = font_bold
    ws2["F2"] = "Zirakpur, Punjab - 140604"
    ws2["F2"].font = font_normal

    ws2["A3"] = "License No. SLA-7777 Expiry: 26/10/2027"
    ws2["A3"].font = font_normal
    ws2["F3"] = "Mob: 9814035162"
    ws2["F3"].font = font_normal

    ws2["A4"] = "IISLA Membership: F/N/05949"
    ws2["A4"].font = font_normal
    ws2["F4"] = "jd.batta8810@gmail.com"
    ws2["F4"].font = font_normal

    # Banner
    ws2.merge_cells("A6:G6")
    ws2["A6"] = "SURVEY FEE BILL / TAX INVOICE"
    ws2["A6"].fill = navy_header_fill
    ws2["A6"].font = font_title
    ws2["A6"].alignment = Alignment(horizontal="center", vertical="center")
    ws2.row_dimensions[6].height = 28

    ws2["A8"] = "Bill Ref:"
    ws2["B8"] = "JDB/2026-27/UIIC/8744"
    ws2["A8"].font = font_bold
    ws2["B8"].font = font_bold

    ws2["D8"] = "Date:"
    ws2["E8"] = "25/04/2026"
    ws2["D8"].font = font_bold
    ws2["E8"].font = font_normal

    ws2["A10"] = "INSURERS"
    ws2["B10"] = "United India Insurance Company Limited"
    ws2["A10"].font = font_bold

    ws2["D10"] = "POLICY NO."
    ws2["E10"] = "1103003122P113572944"
    ws2["D10"].font = font_bold

    ws2["A11"] = "CLAIM NO."
    ws2["B11"] = "2230003126C065430001"
    ws2["A11"].font = font_bold
    ws2["B11"].font = font_bold

    ws2["D11"] = "VEHICLE NO."
    ws2["E11"] = "DL-3S-EK-1646"
    ws2["D11"].font = font_bold

    ws2["A12"] = "INSURED"
    ws2["B12"] = "AJAY SINGH"
    ws2["A12"].font = font_bold

    ws2["D12"] = "MAKE"
    ws2["E12"] = "Kawasaki Ninja ZX-10R"
    ws2["D12"].font = font_bold

    # Fee Items Table
    ws2.merge_cells("A14:G14")
    ws2["A14"] = "FEE & EXPENSES PARTICULARS"
    ws2["A14"].fill = sub_header_fill
    ws2["A14"].font = font_sub_title
    ws2["A14"].alignment = Alignment(horizontal="left", vertical="center", indent=1)

    fee_headers = ["S.N.", "PARTICULARS / DESCRIPTION", "QTY / KMS", "RATE", "AMOUNT (Rs.)"]
    for c_idx, h_text in enumerate(fee_headers, start=1):
        cell = ws2.cell(row=15, column=c_idx, value=h_text)
        cell.font = font_bold
        cell.fill = section_fill
        cell.border = thin_border
        cell.alignment = Alignment(horizontal="center", vertical="center")

    fee_items = [
        (1, "SURVEY FEE", "1 Final Survey", 2500.0, 2500.0),
        (2, "REINSPECTION FEE", "1 Re-inspection", 750.0, 750.0),
        (3, "CONVEYANCE CHARGES", "25 Kms @ 20/Km", 20.0, 500.0),
        (4, "DAILY ALLOWANCE", "Local Allowance", 250.0, 250.0),
        (5, "PHOTOGRAPHS", "15 Photos @ 20/Photo", 20.0, 300.0),
    ]

    for r_idx, f_row in enumerate(fee_items, start=16):
        for c_idx, val in enumerate(f_row, start=1):
            cell = ws2.cell(row=r_idx, column=c_idx, value=val)
            cell.font = font_normal
            cell.border = thin_border
            if c_idx in (4, 5):
                cell.number_format = "#,##0.00"
                cell.alignment = Alignment(horizontal="right")
            elif c_idx == 1:
                cell.alignment = Alignment(horizontal="center")

    # Totals
    ws2["B21"] = "PROFESSIONAL FEE"
    ws2["E21"] = 3250.0  # Survey fee (2500) + Reinspection fee (750)
    ws2["B21"].font = font_bold
    ws2["E21"].font = font_bold
    ws2["E21"].number_format = "#,##0.00"
    ws2["E21"].fill = highlight_fill

    ws2["B22"] = "TOTAL EXPENSES (Conveyance + Photos + DA)"
    ws2["E22"] = 1050.0
    ws2["B22"].font = font_bold
    ws2["E22"].font = font_bold
    ws2["E22"].number_format = "#,##0.00"

    ws2["B23"] = "TOTAL CLAIMED AMOUNT"
    ws2["E23"] = 4300.0  # Sum of professional fee + conveyance + photos + DA
    ws2["B23"].font = font_bold
    ws2["E23"].font = font_bold
    ws2["E23"].number_format = "#,##0.00"
    ws2["E23"].fill = highlight_fill

    ws2["B24"] = "GST 18% (CGST 9% + SGST 9%)"
    ws2["E24"] = 774.0
    ws2["B24"].font = font_bold
    ws2["E24"].font = font_bold
    ws2["E24"].number_format = "#,##0.00"

    ws2["B25"] = "GRAND TOTAL PAYABLE"
    ws2["E25"] = 5074.0
    ws2["B25"].font = font_bold
    ws2["E25"].font = font_bold
    ws2["E25"].number_format = "#,##0.00"
    ws2["B25"].fill = total_fill
    ws2["E25"].fill = total_fill
    ws2["B25"].border = double_bottom
    ws2["E25"].border = double_bottom

    # Bank details
    ws2["A27"] = "BANK DETAILS FOR NEFT / RTGS PAYMENT:"
    ws2["A27"].font = font_bold
    ws2["A28"] = "Beneficiary: Jeewan Deep Batta | Bank: HDFC Bank Ltd | A/C No: 50200012345678 | IFSC: HDFC0001234 | Branch: Zirakpur"
    ws2["A28"].font = font_normal

    for col_letter, width in {"A": 10, "B": 36, "C": 22, "D": 18, "E": 20, "F": 20, "G": 16}.items():
        ws2.column_dimensions[col_letter].width = width

    # =========================================================================
    # SHEET 3: Re-inspection
    # (Matches index 2 extraction in folder_scanner.py for reinspection.xlsx)
    # =========================================================================
    ws3 = wb.create_sheet(title="Re-inspection")
    ws3.views.sheetView[0].showGridLines = True

    # 1. Letterhead
    ws3["A1"] = "JEEWAN DEEP BATTA"
    ws3["A1"].font = Font(name="Calibri", size=13, bold=True, color="1A365D")
    ws3["E1"] = "17/102, Royal Estate"
    ws3["F1"] = "Zirakpur, Punjab - 140604"

    ws3["A2"] = "Surveyor & Loss Assessor"
    ws3["A2"].font = font_bold
    ws3["E2"] = "Mob: 9814035162"
    ws3["F2"] = "jd.batta8810@gmail.com"

    # Banner
    ws3.merge_cells("A4:F4")
    ws3["A4"] = "PRIVATE & CONFIDENTIAL MOTOR RE-INSPECTION SURVEY REPORT"
    ws3["A4"].fill = navy_header_fill
    ws3["A4"].font = font_title
    ws3["A4"].alignment = Alignment(horizontal="center", vertical="center")
    ws3.row_dimensions[4].height = 28

    ws3["A6"] = "Ref:"
    ws3["B6"] = "JDB/2026-27/UIIC/8744"
    ws3["A6"].font = font_bold
    ws3["B6"].font = font_bold

    ws3["D6"] = "Date:"
    ws3["E6"] = "25/04/2026"
    ws3["D6"].font = font_bold
    ws3["E6"].font = font_normal

    ws3["A8"] = "Insured"
    ws3["B8"] = "AJAY SINGH"
    ws3["A8"].font = font_bold

    ws3["D8"] = "Policy No."
    ws3["E8"] = "1103003122P113572944"
    ws3["D8"].font = font_bold

    ws3["A9"] = "Claim Number"
    ws3["B9"] = "2230003126C065430001"
    ws3["A9"].font = font_bold

    ws3["D9"] = "Registration No."
    ws3["E9"] = "DL-3S-EK-1646"
    ws3["D9"].font = font_bold

    ws3["A10"] = "Date of Survey"
    ws3["B10"] = "20/04/2026"
    ws3["A10"].font = font_bold

    ws3["D10"] = "Date of Re-inspection"
    ws3["E10"] = "25/04/2026"
    ws3["D10"].font = font_bold

    # Certificate
    ws3.merge_cells("A12:F12")
    ws3["A12"] = "RE-INSPECTION CERTIFICATE & FINDINGS"
    ws3["A12"].fill = sub_header_fill
    ws3["A12"].font = font_sub_title
    ws3["A12"].alignment = Alignment(horizontal="left", vertical="center", indent=1)

    ws3["A14"] = (
        "I have re-inspected the captioned vehicle (DL-3S-EK-1646) at the repairer workshop after completion of repairs. "
        "I have verified that all replacements and repairs allowed in our Final Survey Report have been carried out satisfactorily. "
        "All replaced parts (Cowling, Headlamp, Fender, Brackets, Levers) were physically inspected and verified as genuine new parts. "
        "The salvage parts were physically checked and the salvage destruction process was carried out in my presence. "
        "Photographs of the repaired vehicle, engine number, chassis number, and destructed salvage have been taken and attached. "
        "The vehicle was found to be in thoroughly roadworthy condition at the time of my re-inspection."
    )
    ws3["A14"].font = font_normal
    ws3["A14"].alignment = Alignment(wrap_text=True, vertical="top")
    ws3.merge_cells("A14:F17")

    # Item verification checklist
    ws3["A19"] = "S.N."
    ws3["B19"] = "ITEM / WORK DESCRIPTION"
    ws3["C19"] = "STATUS"
    ws3["D19"] = "VERIFICATION RESULT"
    ws3["E19"] = "REMARKS"
    for c in ["A19", "B19", "C19", "D19", "E19"]:
        ws3[c].font = font_bold
        ws3[c].fill = section_fill
        ws3[c].border = thin_border

    reinspect_items = [
        (1, "Upper Cowling & Windscreen", "Replaced", "Verified New Part", "Properly Fitted"),
        (2, "Headlight Assembly", "Replaced", "Verified Working", "Alignment OK"),
        (3, "Front Fender (Plastic)", "Replaced", "Verified New Part", "Paint Finish OK"),
        (4, "Fuel Tank Outer Cover", "Repaired & Painted", "Verified Finish", "Paint Match OK"),
        (5, "Brake Lever & Cylinder", "Replaced", "Verified Genuine", "Pressure Check OK"),
        (6, "Salvage Destruction", "Completed", "Destructed on Site", "Photos Attached"),
    ]
    for r_idx, (sn, item, status, res, rem) in enumerate(reinspect_items, start=20):
        ws3.cell(row=r_idx, column=1, value=sn).alignment = Alignment(horizontal="center")
        ws3.cell(row=r_idx, column=2, value=item)
        ws3.cell(row=r_idx, column=3, value=status)
        ws3.cell(row=r_idx, column=4, value=res)
        ws3.cell(row=r_idx, column=5, value=rem)
        for c in range(1, 6):
            ws3.cell(row=r_idx, column=c).border = thin_border
            ws3.cell(row=r_idx, column=c).font = font_normal

    ws3["A28"] = "The report is issued without prejudice."
    ws3["A28"].font = font_small

    ws3["A30"] = "Jeewan Deep Batta"
    ws3["A30"].font = font_bold
    ws3["A31"] = "Surveyor & Loss Assessor"
    ws3["A31"].font = font_normal

    for col_letter, width in {"A": 10, "B": 36, "C": 20, "D": 24, "E": 24, "F": 20}.items():
        ws3.column_dimensions[col_letter].width = width

    # Save workbook
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    wb.save(output_path)
    print(f"Workbook successfully saved to: {output_path}")

if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "dummy_uiic_testing.xlsx"
    create_uiic_dummy_workbook(out)
