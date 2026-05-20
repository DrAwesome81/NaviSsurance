import json
from pathlib import Path
from file_handler import extract_text_from_pdf, extract_text_from_docx  # Your extract functions

# Dataset prep from regulatory SOPs/standards supports fine-tuning local models for Pulse private memory, Intel raising, and 🛡️ Shield compliance analysis (new data pipeline coordination)
# Define file paths for SOPs and standards (update these to match your actual paths)
# Prepares regulatory data for fine-tuning supporting Pulse private memory and Shield offline (additional data prep coordination)
reports = [
    {
        "sop_path": "C:/Users/adamo/Downloads/SOP015_Labelling__Identification_and_Traceability_Rev0.2.pdf",
        "standard_path": "C:/Users/adamo/Dropbox/_Consulting/Quality Assurance/_Standards Documents/ISO/Current/002_iso13485_2016.pdf",
        "output": {
            "overview": "SOP015 outlines procedures for labelling, identification, and traceability at DOVA Health Intelligence Inc., covering general principles, labelling design/content/storage/operations, Unique Device Identifier (UDI), device traceability, and software requirements. It is a draft (Rev 0.2) and applies to all components, packaging, and devices developed/manufactured/serviced by the organization. The relevant ISO 13485:2016 requirements for these areas are primarily in Clause 7 (Product Realization), specifically 7.5.8 (Identification), 7.5.9 (Traceability), and 7.5.11 (Preservation of product), with related clauses in 4.1, 4.2.4, 7.1, 7.2, and 8.3. Overall, SOP015 is moderately aligned with ISO 13485:2016. It provides a structured procedure for labelling (6.2), UDI (6.3), traceability (6.4), and software ID (6.5), with emphasis on regulatory compliance (e.g., FDA/EU MDR/Health Canada guidelines in 6.2.1.1) and controls to prevent mix-ups (6.2.3.3). It integrates responsibilities (3) and references related SOPs (4). However, gaps exist in explicit risk management integration, validation of labelling processes, detailed nonconforming product handling for labels, and full traceability records. The SOP is draft-status, so it's not yet 'documented and maintained' as per ISO.",
            "key_alignments": "- Documented Procedures: The SOP itself serves as the required documented procedure for identification (6.1), labelling (6.2), UDI (6.3), and traceability (6.4), identifying product by suitable means (e.g., UDI, lot/batch in 6.3.1.2, 6.4.2) throughout realization, as per 7.5.8.\n- Traceability System: Section 6.4 establishes a traceability system to track acceptance status and movement (6.4.1), maintaining Device History Records (DHR) with UDI, production ID, inspection records, packaging/labelling details, distribution records, and component IDs (6.4.2), aligning with 7.5.9 requirements for documented traceability and records.\n- Labelling Controls: Section 6.2 documents labelling design/content (6.2.1), materials/equipment (6.2.2), storage/operations/inspection (6.2.3), process (6.2.4), ensuring labels are verified (6.2.4.1), securely affixed (6.2.4.2), inspected (6.2.4.3), and documented in DHR (6.2.3.2, 6.2.3.4), supporting 7.5.11 preservation (prevent damage/mix-ups) and 4.2.4 document control (approval, distribution).\n- UDI Requirements: Detailed UDI definition (6.3.1.1), composition (DI/PI, barcode in 6.3.1.3), labelling (6.3.2), PI placement (6.3.3), material durability (6.3.4), verification/audits (6.3.5), meeting 7.5.8 unique ID and regulatory traceability.\n- Software ID: Section 6.5 identifies software by versioning (6.5.1) and acceptance via deployment records (6.5.2), aligning with 7.5.8 for software as product.\n- Responsibilities and Communication: Section 3 defines roles (Top Management, Quality/Regulatory, Manufacturing/Operations, All Employees), ensuring authority/communication as per 5.5.1, and training (3, 6.2.1.3) for competence per 6.2.",
            "improvements": [
                {
                    "section": "6.2 Labelling",
                    "issue": "SOP015 lacks documented risk assessment for labelling errors (e.g., mix-ups in 6.2.3.3) or UDI placement (6.3.2), no mention of evaluating risks in labelling design (6.2.1) or process (6.2.4), despite ISO requiring risk management in product realization.",
                    "fix": "Add a section for risk analysis (e.g., FMEA for labelling/UDI processes), integrate into planning (6.2.1.1), and document in DHR (6.4.2). Reference ISO 14971 for methods. Update to state: 'Risk assessment shall be conducted for labelling and traceability processes to identify potential nonconformities.'",
                    "reference": "7.1 Planning of product realization: 'The organization shall document one or more processes for risk management in product realization.'"
                },
                {
                    "section": "6.2 Labelling Process",
                    "issue": "No documented validation for labelling operations (6.2.3/6.2.4) or UDI verification (6.3.5), e.g., no methods/criteria for ensuring labels meet requirements (legibility in 6.2.4.1, durability in 6.3.4.1), where output can't be verified by monitoring (e.g., long-term adhesion).",
                    "fix": "Add validation procedures (methods, criteria, sample size) for labelling/UDI processes prior to implementation, revalidate on changes. Document plans per 7.5.6 a-g.",
                    "reference": "7.5.6 Validation of processes for production and service provision: 'The organization shall validate any processes for production and service provision where the resulting output cannot be or is not verified by subsequent monitoring or measurement... The organization shall document procedures for validation...'"
                },
                {
                    "section": "6.2 Labelling Storage, Operations and Inspection",
                    "issue": "No explicit procedure for nonconforming labels (e.g., errors in 6.2.4.3) or traceability issues (e.g., missing DHR in 6.4.2), no segregation/evaluation/disposition, despite ISO requiring control to prevent unintended use.",
                    "fix": "Add a section for identifying/controlling nonconforming labels (inspection in 6.2.3.5), reference corrective action SOP, document in DHR. Include evaluation for investigation/notification.",
                    "reference": "8.3 Control of nonconforming product: 'The organization shall ensure that product which does not conform to product requirements is identified and controlled to prevent its unintended use or delivery. The organization shall document a procedure to define the controls and related responsibilities and authorities for the identification, documentation, segregation, evaluation and disposition of nonconforming product.'"
                },
                {
                    "section": "6.3 Unique Device Identifier",
                    "issue": "Audits mentioned in 6.3.5.4 but no frequency/criteria for reviewing labelling/UDI processes (6.2/6.3) or traceability system (6.4), no link to QMS audits.",
                    "fix": "Add periodic review (annual or per SOP008), with checklist for compliance (legibility, UDI accuracy), integrate with internal audits per 8.2.4.",
                    "reference": "8.2.4 Internal audit: 'The organization shall conduct internal audits at planned intervals to determine whether the quality management system: a) conforms to planned and documented arrangements, requirements of this International Standard... The organization shall document a procedure to describe the responsibilities and requirements for planning and conducting audits...'"
                }
            ],
            "recommendations": "Revise SOP015 to Rev 0.3 incorporating these changes (risk/validation/nonconforming/audit integration), with Quality/Regulatory approval per responsibilities in 3. Retrain Manufacturing/Operations on new risk/validation processes, emphasizing UDI verification (6.3.5) and nonconforming handling, per 6.2. In next internal audit (per 8.2.4), verify labelling/traceability records for these elements. No Major Nonconformities: These are enhancements; the SOP is compliant for basic operations, but addressing them reduces risk in regulatory audits (e.g., FDA per 7.1). Integrate with risk management SOP for labelling risks."
        }
    },
    {
        "sop_path": "C:/Users/adamo/Downloads/Quality_System_Manual_Part_1_Overview.docx",
        "standard_path": "C:/Users/adamo/Dropbox/_Consulting/Quality Assurance/_Standards Documents/ISO/Current/002_iso13485_2016.pdf",
        "output": {
            "overview": "The assessed document 'Quality_System_Manual_Part_1_Overview.docx' provides a high-level overview of the company's Quality System Manual (QSM), including purpose, background, scope, terms, framework, exclusions, and management responsibility. It aligns generally with ISO 13485:2016 requirements for establishing a quality management system (Clause 4), but lacks detailed processes and specific references to many clauses. The reference document '002_iso13485_2016.pdf' is the full ISO 13485:2016 standard, specifying requirements for QMS in medical devices. The assessed manual demonstrates basic commitment to QMS ('The overall goal of our quality system is to meet customer and regulatory requirements by providing safe and effective medical devices') but excludes some elements without full justification as per Clause 1 Scope, and does not fully detail implementation as required in Clause 4.1 General requirements.",
            "key_alignments": "- Scope and Exclusions: Assessed 'This manual applies to all medical device products designed, developed, produced, sold, distributed, installed, or serviced by the Company' aligns with reference Clause 1 Scope: 'This International Standard specifies requirements for a quality management system where an organization needs to demonstrate its ability to provide medical devices and related services that consistently meet customer and applicable regulatory requirements.' It lists exclusions with justification ('The following table identifies requirements not applicable to our organization due to the nature of our medical devices'), matching reference 'If any requirement(s) in Clauses 6, 7 or 8 of this International Standard is(are) not applicable due to the activities undertaken by the organization or the nature of the medical device for which the quality management system is applied, the organization does not need to include such a requirement(s) in its quality management system.'\n- Framework and Process Approach: Assessed 'An overview diagram showing the Company core processes and how they interrelate is shown in the Framework section 7.1.2' and 'Quality Management System Process Interaction Diagram' aligns with reference 0.3 Process approach: 'This International Standard is based on a process approach to quality management. Any activity that receives input and converts it to output can be considered as a process.' It also notes 'a risk-based approach is applied to the control of the appropriate processes needed for the QS', matching reference 0.2 Clarification of concepts: 'A requirement is considered appropriate if it is necessary for the organization to manage risks.'\n- Management Responsibility: Assessed 'The Company top management is committed to establishing and maintaining the effectiveness of the Company’s QS and quality policy' and details commitment, planning, organization aligns with reference Clause 5 Management responsibility, e.g., 5.1 Management commitment: 'Top management shall provide evidence of its commitment to the development and implementation of the quality management system and maintenance of its effectiveness by: a) communicating to the organization the importance of meeting customer as well as applicable regulatory requirements.'\n- Resource Management: Assessed 'Top management determines and provides the resources needed to implement the QS' aligns with reference Clause 6.1 Provision of resources: 'The organization shall determine and provide the resources needed to: a) implement the quality management system and to maintain its effectiveness.'\n- Product Realization: Assessed covers planning, customer processes, design, purchasing, measurement aligns with reference Clause 7 Product realization, e.g., 7.1 Planning of product realization: 'The organization shall plan and develop the processes needed for product realization.'\n- Measurement, Analysis and Improvement: Assessed mentions feedback, audits, nonconforming product, data analysis, improvement aligns with reference Clause 8 Measurement, analysis and improvement, e.g., 8.1 General: 'The organization shall plan and implement the monitoring, measurement, analysis and improvement processes needed to: a) demonstrate conformity of product.'",
            "improvements": [
                {
                    "section": "Exclusions",
                    "issue": "The assessed document lists exclusions but does not fully document the justification in the manual itself (only refers to 'the following table identifies requirements not applicable'), and does not record the justification as per reference 'For any clause that is determined to be not applicable, the organization records the justification as described in 4.2.2.'",
                    "fix": "Expand the exclusions table in the assessed manual to include detailed justification for each exclusion, and reference Clause 4.2.2 for recording, ensuring 'None of these non-applications affects our ability or responsibility to provide safe and effective devices that meet customer and regulatory requirements.' is explicitly tied to each.",
                    "reference": "Clause 1 Scope: 'If any requirement(s) in Clauses 6, 7 or 8 of this International Standard is(are) not applicable due to the activities undertaken by the organization or the nature of the medical device for which the quality management system is applied, the organization does not need to include such a requirement(s) in its quality management system. For any clause that is determined to be not applicable, the organization records the justification as described in 4.2.2.'"
                },
                {
                    "section": "General (Quality Management System)",
                    "issue": "The assessed document describes the QMS but does not explicitly document procedures for validation of computer software used in the QMS (e.g., eQMS mentioned in 'Electronically-signed PDF copies of documents stored in Enzyme eQMS'), as required by reference 'The organization shall document procedures for the validation of the application of computer software used in the quality management system.'",
                    "fix": "Add a section or reference to SOP for software validation, including 'Such software applications shall be validated prior to initial use and, as appropriate, after changes to such software or its application. The specific approach and activities associated with software validation and revalidation shall be proportionate to the risk associated with the use of the software.'",
                    "reference": "Clause 4.1.6: 'The organization shall document procedures for the validation of the application of computer software used in the quality management system. Such software applications shall be validated prior to initial use and, as appropriate, after changes to such software or its application.'"
                },
                {
                    "section": "Framework",
                    "issue": "The assessed document includes a process interaction diagram but does not explicitly address risk management in product realization as part of planning, only mentioning 'a risk-based approach is applied to the control of the appropriate processes needed for the QS' without documentation, as required by reference 'The organization shall document one or more processes for risk management in product realization.'",
                    "fix": "Add details to the framework section or reference a risk management SOP, including 'Records of risk management activities shall be maintained (see 4.2.5)', and integrate risk into the process diagram.",
                    "reference": "Clause 7.1 Planning of product realization: 'The organization shall document one or more processes for risk management in product realization. Records of risk management activities shall be maintained (see 4.2.5).'"
                },
                {
                    "section": "Document, Data and Record Control",
                    "issue": "The assessed document mentions document control but does not detail controls for identification, storage, protection, retrieval, retention, and disposition of records, nor protection of confidential health information, as per reference 'The organization shall document procedures to define the controls needed for the identification, storage, security and integrity, retrieval, retention time and disposition of records. The organization shall define and implement methods for protecting confidential health information contained in records in accordance with the applicable regulatory requirements.'",
                    "fix": "Expand the section to include documented procedures for record controls, e.g., 'Records shall be maintained to provide evidence of conformity to requirements and of the effective operation of the quality management system... Records shall remain legible, readily identifiable and retrievable.'",
                    "reference": "Clause 4.2.5 Control of records: 'Records shall be maintained to provide evidence of conformity to requirements and of the effective operation of the quality management system. The organization shall document procedures to define the controls needed for the identification, storage, security and integrity, retrieval, retention time and disposition of records. The organization shall define and implement methods for protecting confidential health information contained in records in accordance with the applicable regulatory requirements. Records shall remain legible, readily identifiable and retrievable. Changes to a record shall remain identifiable.'"
                },
                {
                    "section": "Management Responsibility",
                    "issue": "The assessed document covers management commitment but does not explicitly require top management to appoint a management representative with responsibility for ensuring QMS processes are documented and reporting on effectiveness, as per reference 'Top management shall appoint a member of management who, irrespective of other responsibilities, has responsibility and authority that includes: a) ensuring that processes needed for the quality management system are documented; b) reporting to top management on the effectiveness of the quality management system and any need for improvement.'",
                    "fix": "Add a subsection for Management Representative, e.g., 'The QS Management Representative (MR) ensures the processes needed for the QS are documented, and the MR reports to top management on the effectiveness and maintenance of the QS and any need for improvement.'",
                    "reference": "Clause 5.5.2 Management representative: 'Top management shall appoint a member of management who, irrespective of other responsibilities, has responsibility and authority that includes: a) ensuring that processes needed for the quality management system are documented; b) reporting to top management on the effectiveness of the quality management system and any need for improvement; c) ensuring the promotion of awareness of applicable regulatory requirements and quality management system requirements throughout the organization.'"
                },
                {
                    "section": "Resource Management",
                    "issue": "The assessed document mentions provision of resources but does not document requirements for work environment or contamination control, nor maintenance for infrastructure/equipment, as per reference 'The organization shall document the requirements for the infrastructure needed to achieve conformity to product requirements... The organization shall document requirements for the maintenance activities... The organization shall document the requirements for the work environment needed to achieve conformity to product requirements.'",
                    "fix": "Add sections for Infrastructure (including maintenance records) and Work Environment (e.g., 'If the conditions for the work environment can have an adverse effect on product quality, the organization shall document procedures for monitoring and control of the work environment.'), with records maintained.",
                    "reference": "Clause 6.3 Infrastructure: 'The organization shall document the requirements for the infrastructure needed to achieve conformity to product requirements, prevent product mix-up and ensure orderly handling of product... The organization shall document requirements for the maintenance activities, including the interval of performing the maintenance activities, when such maintenance activities, or lack thereof, can affect product quality.' Clause 6.4 Work environment and contamination control: 'The organization shall document the requirements for the work environment needed to achieve conformity to product requirements. If the conditions for the work environment can have an adverse effect on product quality, the organization shall document procedures for monitoring and control of the work environment.'"
                },
                {
                    "section": "Product Realization",
                    "issue": "The assessed document covers high-level product realization but does not detail validation of processes where output can't be verified (e.g., sterilization if applicable, or software validation), nor unique device identification if required, as per reference 'The organization shall validate any processes for production and service provision where the resulting output cannot be or is not verified by subsequent monitoring or measurement... If required by applicable regulatory requirements, the organization shall document a system to assign unique device identification to the medical device.'",
                    "fix": "Expand to include process validation procedures (methods, criteria, revalidation), and UDI system if applicable, with records. Reference 'The specific approach and activities associated with software validation and revalidation shall be proportionate to the risk associated with the use of the software.'",
                    "reference": "Clause 7.5.6 Validation of processes for production and service provision: 'The organization shall validate any processes for production and service provision where the resulting output cannot be or is not verified by subsequent monitoring or measurement and, as a consequence, deficiencies become apparent only after the product is in use or the service has been delivered... The organization shall document procedures for validation of processes, including: a) defined criteria for review and approval of the processes.' Clause 7.5.8 Identification: 'If required by applicable regulatory requirements, the organization shall document a system to assign unique device identification to the medical device.'"
                },
                {
                    "section": "Measurement, Analysis and Improvement",
                    "issue": "The assessed document mentions monitoring/measurement but does not detail complaint handling procedures or reporting to regulatory authorities, nor preventive action for potential nonconformities, as per reference 'The organization shall document procedures for timely complaint handling in accordance with applicable regulatory requirements... If applicable regulatory requirements require notification of complaints that meet specified reporting criteria of adverse events or issuance of advisory notices, the organization shall document procedures for providing notification to the appropriate regulatory authorities.'",
                    "fix": "Add detailed complaint handling (receiving, investigating, reporting) and preventive action procedures, with records. Include 'The organization shall determine action to eliminate the causes of potential nonconformities in order to prevent their occurrence.'",
                    "reference": "Clause 8.2.2 Complaint handling: 'The organization shall document procedures for timely complaint handling in accordance with applicable regulatory requirements. These procedures shall include at a minimum requirements and responsibilities for: a) receiving and recording information; b) evaluating information to determine if the feedback constitutes a complaint; c) investigating complaints...' Clause 8.5.3 Preventive action: 'The organization shall determine action to eliminate the causes of potential nonconformities in order to prevent their occurrence. Preventive actions shall be proportionate to the effects of the potential problems.' Clause 8.2.3 Reporting to regulatory authorities: 'If applicable regulatory requirements require notification of complaints that meet specified reporting criteria of adverse events or issuance of advisory notices, the organization shall document procedures for providing notification to the appropriate regulatory authorities.'"
                }
            ],
            "recommendations": "To fully align with ISO 13485, expand the assessed manual with detailed sections on software validation (Clause 4.1.6, 7.5.6), risk management processes (Clause 7.1), nonconforming product control (Clause 8.3), and complaint handling/reporting (Clauses 8.2.2, 8.2.3). Ensure all procedures are documented, with records maintained (Clause 4.2.5). Conduct internal audits to verify implementation (Clause 8.2.4). Update the exclusions justification to explicitly reference Clause 4.2.2, and integrate risk-based thinking throughout (Clause 0.2)."
        }
    },
    {
        "sop_path": "C:/Users/adamo/Downloads/Software_Development_Life_Cycle_SOP_Template.docx",
        "standard_path": "C:/Users/adamo/Dropbox/_Consulting/Quality Assurance/_Standards Documents/IEC/006_bs_en_62304_2006.pdf",
        "output": {
            "overview": "The assessed document 'Software Development Life Cycle SOP - Template.docx' outlines the software development process for medical devices at [Company], using an Agile approach with four phases: Planning, Development, Verification and Validation (V&V), and Design Transfer. It references IEC 62304:2006 + A1:2015 among other standards and details deliverables, responsibilities, and risk management. The reference document '006_bs en 62304 -2006.pdf' is the IEC 62304:2006 standard, defining lifecycle processes for medical device software. The SOP aligns well with IEC 62304's software development (Clause 5), risk management (Clause 7), configuration management (Clause 8), and problem resolution (Clause 9) processes, but lacks explicit details on software safety classification updates, SOUP management, and maintenance plan specifics.",
            "key_alignments": "- Software Development Process: Assessed SOP's four phases (7) align with reference Clause 5 Software development PROCESS: 'The MANUFACTURER shall establish a software development plan (or plans) for conducting the ACTIVITIES and TASKS of the software development PROCESS.' The SOP’s Planning (9), Development (10), V&V (11), and Design Transfer (12) map to 5.1 (planning), 5.2-5.4 (requirements, architecture, design), 5.5-5.7 (integration, testing), and 5.8 (release).\n- Risk Management: Assessed 9.5 and 10.3 detail a Risk Management Plan and Risk Assessment per [Risk Management SOP], aligning with reference Clause 7 Software RISK MANAGEMENT PROCESS: 'The MANUFACTURER shall identify SOFTWARE ITEMS that could contribute to a hazardous situation' (7.1) and 'shall document in the RISK MANAGEMENT FILE sequences of events' (7.1.5).\n- Configuration Management: Assessed 6.2 references [Configuration Management SOP] for change control, aligning with reference Clause 8 Software configuration management PROCESS: 'The MANUFACTURER shall include or reference software configuration management information in the software development plan' (5.1.9).\n- Problem Resolution: Assessed 11.3 and 14.4-14.5 cover defect tracking and nonconformance handling, aligning with reference Clause 9 Software problem resolution PROCESS: 'The MANUFACTURER shall maintain records of PROBLEM REPORTS and their resolution including their VERIFICATION' (9.5).\n- Deliverables and Documentation: Assessed 13 lists deliverables (e.g., Software Development Plan, SRS, SAD, Traceability Matrix) maintained in eQMS, aligning with reference 5.1.1: 'The MANUFACTURER shall establish a software development plan (or plans) for conducting the ACTIVITIES and TASKS of the software development PROCESS.'",
            "improvements": [
                {
                    "section": "9.4 Software Safety Classification",
                    "issue": "The SOP defines software safety classification (9.4.1.1-9.4.1.3) per IEC 62304 (Class A, B, C) but does not address re-evaluation of safety classification after changes or during maintenance, as required by reference 'The MANUFACTURER shall analyse changes to the MEDICAL DEVICE SOFTWARE (including SOUP) with respect to SAFETY' (7.4.1).",
                    "fix": "Add a section to 9.4 or 14.2 requiring re-evaluation of software safety classification post-changes, documenting in the Risk Management File, e.g., 'The MANUFACTURER shall re-EVALUATE the software safety class when changes are made to the SOFTWARE SYSTEM.'",
                    "reference": "Clause 7.4.1 Analyse changes to MEDICAL DEVICE SOFTWARE with respect to SAFETY: 'The MANUFACTURER shall analyse changes to the MEDICAL DEVICE SOFTWARE (including SOUP) with respect to SAFETY.'"
                },
                {
                    "section": "10.1.2 Software Detailed Design",
                    "issue": "The SOP mentions SOUP in 10.1.2 but lacks procedures for documenting and verifying SOUP items, as required by reference 'The MANUFACTURER shall document: a) the title, b) the MANUFACTURER, and c) the unique SOUP designator of each SOUP CONFIGURATION ITEM being used' (7.1.2).",
                    "fix": "Expand 10.1.2 to include SOUP documentation (title, manufacturer, version) and verification requirements, e.g., 'The MANUFACTURER shall document the title, MANUFACTURER, and unique designator for each SOUP item in the Software Detailed Design.'",
                    "reference": "Clause 7.1.2 Identify SOFTWARE ITEMS that could contribute to a hazardous situation: 'The MANUFACTURER shall document: a) the title, b) the MANUFACTURER, and c) the unique SOUP designator of each SOUP CONFIGURATION ITEM being used.'"
                },
                {
                    "section": "14.1 Software Maintenance Process",
                    "issue": "The SOP references [Change Control SOP] and [Configuration Management SOP] for maintenance but does not detail a software maintenance plan, as required by reference 'The MANUFACTURER shall establish a software maintenance plan (or plans) for conducting the ACTIVITIES and TASKS of the maintenance PROCESS' (6.1).",
                    "fix": "Add a section to 14.1 or reference a maintenance plan in [Change Control SOP], including procedures for maintenance activities and tasks, e.g., 'The MANUFACTURER shall establish a software maintenance plan for conducting the ACTIVITIES and TASKS of the maintenance PROCESS.'",
                    "reference": "Clause 6.1 Establish software maintenance plan: 'The MANUFACTURER shall establish a software maintenance plan (or plans) for conducting the ACTIVITIES and TASKS of the maintenance PROCESS.'"
                },
                {
                    "section": "10.4 Verification and Validation Plan",
                    "issue": "The SOP includes a V&V Plan (10.4) but does not explicitly require verification of risk control measures implemented in software, as per reference 'The MANUFACTURER shall verify each RISK CONTROL measure implemented in software' (7.3.1).",
                    "fix": "Update 10.4 to include verification of risk control measures, e.g., 'The Verification and Validation Plan shall include verification of each RISK CONTROL measure implemented in software, with documented results in the Risk Management File.'",
                    "reference": "Clause 7.3.1 Verify RISK CONTROL measures: 'The MANUFACTURER shall verify each RISK CONTROL measure implemented in software.'"
                }
            ],
            "recommendations": "Revise the SOP to include re-evaluation of software safety classification post-changes (7.4.1), detailed SOUP documentation and verification (7.1.2), a specific software maintenance plan (6.1), and explicit verification of risk control measures (7.3.1). Ensure all deliverables are maintained in eQMS per [Document Control SOP]. Conduct internal audits to verify compliance with IEC 62304 processes, focusing on Class B/C requirements for higher-risk software."
        }
    },
    {
        "sop_path": "C:/Users/adamo/Downloads/SOP023_Approvals_and_Change_Control_Rev2.0.pdf",
        "standard_path": "C:/Users/adamo/Dropbox/_Consulting/Quality Assurance/_Standards Documents/ISO/Current/002_iso13485_2016.pdf",
        "output": {
            "overview": "The compliance report for SOP023 Rev 2.0 (Approvals and Change Control) identifies gaps in change control procedures, particularly in evaluating impacts, verification/validation of changes, and record maintenance. While the SOP provides a structured process for change requests, reviews, and approvals, it lacks specific elements required by ISO 13485:2016 for design and development changes, such as comprehensive impact assessments and traceability records. No positive alignments are explicitly noted, but the SOP's framework supports basic change management. Improvements focus on enhancing evaluation, verification, and documentation to ensure full compliance.",
            "key_alignments": "- Structured Change Request Process: The SOP defines change requests with impact assessment categories (Low, Moderate, Substantial), aligning with ISO 13485:2016's requirement for identifying and reviewing changes.\n- Review and Approval Workflow: The SOP outlines review and approval steps in Enzyme eQMS, supporting ISO 13485:2016's emphasis on controlled changes.\n- Change Impact Assessment: Categorization of change scale provides a risk-based approach, consistent with ISO 13485:2016's risk management integration in change control.",
            "improvements": [
                {
                    "section": "SOP023 Rev 2.0 - Approvals and Change Control - 6.1 Change Requests",
                    "issue": "The procedure for change control does not explicitly address the evaluation of the effect of changes on constituent parts and product in process or already delivered, inputs or outputs of risk management, and product realization processes as required by ISO 13485:2016.",
                    "fix": "Update the change request process to include a specific step for evaluating the impact of changes on constituent parts, products in process or already delivered, risk management inputs/outputs, and product realization processes. This should be documented in the Change Impact assessment criteria.",
                    "reference": "ISO 13485:2016 - Clause 7.3.9 Control of design and development changes"
                },
                {
                    "section": "SOP023 Rev 2.0 - Approvals and Change Control - 6.1.2 Change Impact",
                    "issue": "While the Change Impact assessment categorizes the scale of changes, it does not explicitly require verification and validation (as appropriate) before implementation of changes, which is a requirement for design and development changes under ISO 13485:2016.",
                    "fix": "Revise the Change Impact section to mandate verification and, where appropriate, validation activities for changes classified as 'Moderate' or 'Substantial' before their implementation, ensuring alignment with the standard's requirements for design and development changes.",
                    "reference": "ISO 13485:2016 - Clause 7.3.9 Control of design and development changes (a-c)"
                },
                {
                    "section": "SOP023 Rev 2.0 - Approvals and Change Control - 6.3 Review and Approvals",
                    "issue": "The procedure does not specify that records of changes, their review, and any necessary actions must be maintained, which is a critical requirement for traceability and compliance under ISO 13485:2016.",
                    "fix": "Add a requirement to maintain records of all changes, including details of the review process and any actions taken, within the Enzyme eQMS system or another designated record-keeping mechanism to ensure traceability.",
                    "reference": "ISO 13485:2016 - Clause 7.3.9 Control of design and development changes"
                }
            ],
            "recommendations": "Revise SOP023 to incorporate explicit impact evaluations, mandatory verification/validation for significant changes, and robust record-keeping practices. Conduct a gap analysis against ISO 13485:2016 Clause 7.3.9 to ensure all aspects are covered, and update the SOP accordingly. Train relevant personnel on the revised procedures to maintain compliance."
        }
    },
    {
        "sop_path": "C:/Users/adamo/Downloads/SOP016_Sales_and_Distribution_Rev0.2.pdf",
        "standard_path": "C:/Users/adamo/Dropbox/_Consulting/Quality Assurance/_Standards Documents/ISO/Current/002_iso13485_2016.pdf",
        "output": {
            "overview": "The compliance report for SOP016 (Sales and Distribution, Rev 0.2) identifies gaps in handling customer inquiries, orders, and distribution, particularly in determining/documenting requirements, communication arrangements, review processes, regulatory verification, and record controls. The SOP provides a structured procedure for inquiries, orders, authorizations, and records, but lacks specificity in several areas required by ISO 13485:2016 for customer-related processes (Clause 7.2) and record control (Clause 4.2.5). No major nonconformities, but improvements would enhance compliance and traceability.",
            "key_alignments": "- Customer Inquiries Handling: The SOP coordinates inquiries with relevant teams (Business Development, Engineering), aligning with ISO 13485:2016 Clause 7.2.3 Communication for handling enquiries and contracts.\n- Customer Orders Review: The use of Sales Order Form to resolve ambiguities aligns with Clause 7.2.2 Review of requirements related to product.\n- Authorization to Distribute: The check for regulatory authorization before distribution supports Clause 7.2.1 Determination of requirements related to product (applicable regulatory requirements).\n- Quality Records: Storing Sales Orders and Distribution Logs in Enzyme eQMS aligns with basic record maintenance in Clause 4.2.5 Control of records.",
            "improvements": [
                {
                    "section": "6. Procedure - 7. Customer Inquiries",
                    "issue": "The procedure for handling customer inquiries does not explicitly document the determination of customer requirements as per the standard. It mentions coordination with Business Development and Engineering but lacks specificity on how requirements are identified and documented.",
                    "fix": "Update the procedure to include a step for determining and documenting customer requirements for product information or sales inquiries, ensuring alignment with the process for identifying customer needs.",
                    "reference": "ISO 13485:2016 - Clause 7.2.1 Determination of requirements related to product"
                },
                {
                    "section": "6. Procedure - 7. Customer Inquiries",
                    "issue": "There is no mention of documenting arrangements for communicating with customers regarding product information, enquiries, or order handling, which is a requirement of the standard.",
                    "fix": "Add a detailed process for planning and documenting communication arrangements with customers, including how product information and enquiry responses are handled and recorded.",
                    "reference": "ISO 13485:2016 - Clause 7.2.3 Communication"
                },
                {
                    "section": "6. Procedure - 8. Customer Orders - 10. Sales Orders",
                    "issue": "The procedure for reviewing customer orders (via Sales Order Form) addresses resolving ambiguities but does not explicitly ensure that the organization has the ability to meet defined requirements before acceptance, nor does it confirm user training availability if needed.",
                    "fix": "Enhance the Sales Order review process to include a step confirming the organization's ability to meet customer requirements and availability of user training if required, prior to order acceptance.",
                    "reference": "ISO 13485:2016 - Clause 7.2.2 Review of requirements related to product"
                },
                {
                    "section": "6. Procedure - 8. Customer Orders - 9. Authorization to Distribute Health Software Products",
                    "issue": "While the procedure mentions regulatory authorization for distribution, it does not explicitly address the need to ensure applicable regulatory requirements are met as part of the product distribution process.",
                    "fix": "Incorporate a specific step in the distribution process to verify that all applicable regulatory requirements are met before releasing the product to the customer.",
                    "reference": "ISO 13485:2016 - Clause 7.2.1(c) Determination of requirements related to product"
                },
                {
                    "section": "11. Quality Records",
                    "issue": "The procedure mentions storing Sales Orders and Distribution Logs in Enzyme eQMS but does not specify controls for identification, storage, security, integrity, retrieval, retention time, and disposition of records as required by the standard.",
                    "fix": "Develop and document detailed controls for the management of records in Enzyme eQMS, covering identification, storage, security, integrity, retrieval, retention periods, and disposition methods.",
                    "reference": "ISO 13485:2016 - Clause 4.2.5 Control of records"
                }
            ],
            "recommendations": "Revise SOP016 to include explicit steps for determining and documenting customer requirements (Clause 7.2.1), communication arrangements (Clause 7.2.3), order review confirmation (Clause 7.2.2), regulatory verification in distribution (Clause 7.2.1), and comprehensive record controls (Clause 4.2.5). Ensure all updates are risk-based and proportionate. Conduct training on revised procedures and audit for compliance in next internal review."
        }
    },
    {
        "sop_path": "C:/Users/adamo/Downloads/SOP008_Audits_Rev0.1.pdf",
        "standard_path": "C:/Users/adamo/Dropbox/_Consulting/Quality Assurance/_Standards Documents/ISO/Current/002_iso13485_2016.pdf",
        "output": {
            "overview": "The compliance report for SOP008 (Audits, Rev 0.1) identifies gaps in internal audit frequency planning, execution documentation, report content, and post-audit follow-up. The SOP provides a structured process for audit planning, execution, reporting, and corrective actions, but misses explicit requirements for planned intervals, audit criteria/scope/methods, full record details, and verification reporting. No major nonconformities, but improvements would ensure full alignment with ISO 13485:2016 Clause 8.2.4 for internal audits.",
            "key_alignments": "- Audit Planning: The SOP defines audit types (internal/supplier) and yearly schedule, aligning with Clause 8.2.4: 'The organization shall conduct internal audits at planned intervals to determine whether the quality management system: a) conforms to planned and documented arrangements...'\n- Audit Execution: Use of Audit Form in Enzyme eQMS for criteria/scope/methods supports Clause 8.2.4: 'An audit program shall be planned, taking into consideration the status and importance of the processes and area to be audited...'\n- Post-Audit Activities: Addressing findings via NCs/CAPAs aligns with Clause 8.2.4: 'The audit criteria, scope, interval and methods shall be defined and recorded.'\n- Records Maintenance: Storing Audit Summary Reports in Enzyme eQMS aligns with Clause 4.2.5 Control of records for audit evidence.",
            "improvements": [
                {
                    "section": "SOP008 - Audits - Internal Audit Frequency (6.2.2)",
                    "issue": "The procedure states that all portions of the quality system must be audited annually, but it does not specify that audits must be conducted at 'planned intervals' as required by ISO 13485:2016. While a yearly schedule is mentioned, there is no explicit mention of documenting the intervals or ensuring they are planned based on the status and importance of processes and areas, or results of previous audits.",
                    "fix": "Update the Internal Audit Frequency section to explicitly state that audits are conducted at 'planned intervals' and document how these intervals are determined based on the status, importance of processes, and results of previous audits. Ensure the audit schedule includes these considerations and is documented in the Yearly Audit Schedule.",
                    "reference": "ISO 13485:2016 - Clause 8.2.4"
                },
                {
                    "section": "SOP008 - Audits - Internal Audit Execution (6.2.4)",
                    "issue": "The procedure does not explicitly mention that audit criteria, scope, interval, and methods are defined and recorded for each audit, as required by ISO 13485:2016. While the audit plan is referenced, specific details on documenting these elements are missing.",
                    "fix": "Revise the Executing Internal & Supplier Audits section to include a requirement that audit criteria, scope, interval, and methods are defined and recorded for each audit in the Audit Form on Enzyme eQMS, aligning with the standard's expectations.",
                    "reference": "ISO 13485:2016 - Clause 8.2.4"
                },
                {
                    "section": "SOP008 - Audits - Audit Report (6.6)",
                    "issue": "The Audit Summary Report content does not include the identification of processes and areas audited or the conclusions of the audit, which are required to be part of the audit records as per ISO 13485:2016.",
                    "fix": "Update the Audit Report section to ensure that the Audit Summary Report includes the identification of processes and areas audited, as well as the conclusions of the audit, to meet the documentation requirements of the standard.",
                    "reference": "ISO 13485:2016 - Clause 8.2.4"
                },
                {
                    "section": "SOP008 - Audits - Post-Audit Activities (6.5)",
                    "issue": "While the procedure mentions ensuring audit observations are addressed via NCs and CAPAs, it does not explicitly state that follow-up activities must include verification of actions taken and reporting of verification results, as required by ISO 13485:2016.",
                    "fix": "Enhance the Post-Audit Activities section to explicitly require that follow-up activities include verification of actions taken to address audit findings and the reporting of verification results, ensuring compliance with the standard.",
                    "reference": "ISO 13485:2016 - Clause 8.2.4"
                }
            ],
            "recommendations": "Revise SOP008 to incorporate planned intervals for audits based on process importance and previous results, explicit documentation of audit criteria/scope/methods, comprehensive audit report content, and verification/reporting in follow-up. Update the Yearly Audit Schedule to reflect these, and integrate with CAPA processes. Conduct training on revised audit procedures and verify in next management review to ensure ongoing QMS effectiveness."
        }
    }
]

# Function to load text from file (using your extract functions)
def load_text(path):
    try:
        ext = Path(path).suffix.lower()
        if ext == '.pdf':
            return extract_text_from_pdf(path)
        elif ext == '.docx':
            return extract_text_from_docx(path)
        else:
            return ""
    except Exception as e:
        print(f"Error loading {path}: {e}")
        return ""

# Read fine_tune.jsonl (your provided dataset)
input_reports = []
with open("data/fine_tune.jsonl", "r") as f:
    for line in f:
        input_reports.append(json.loads(line.strip()))

# Create new JSONL with extracted texts and existing outputs
with open("data/fine_tune_formatted.jsonl", "w") as f:
    for input_report, report in zip(input_reports, reports):
        entry = {
            "input": {
                "sop_text": load_text(report["sop_path"]),
                "standard_text": load_text(report["standard_path"])
            },
            "output": input_report  # Use the JSON report from fine_tune.jsonl
        }
        f.write(json.dumps(entry) + "\n")