"""
Document Type Registry for Workspace Generation Engine v2.

This module defines document types and their expected structure/depth.
It is designed to be easily extensible.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DocumentType:
    key: str
    display_name: str
    description: str
    typical_depth: str                    # "concise", "standard", or "exhaustive"
    default_section_structure: list[str]
    depth_guidance: str
    common_cross_references: list[str] = field(default_factory=list)
    notes: str = ""


class DocumentTypeRegistry:
    """
    Central registry of known document types.
    Can be extended at runtime or loaded from configuration in the future.
    """

    def __init__(self):
        self._types: dict[str, DocumentType] = {}
        self._register_default_types()

    def _register_default_types(self):
        # === Design Controls & Validation ===
        self.register(DocumentType(
            key="design_validation_protocol",
            display_name="Design Validation Protocol",
            description="Protocol defining how design validation will be performed.",
            typical_depth="exhaustive",
            default_section_structure=[
                "1. Purpose",
                "2. Scope",
                "3. Responsibilities",
                "4. Definitions and Abbreviations",
                "5. References",
                "6. Validation Strategy and Approach",
                "7. Validation Test Cases / Protocols",
                "8. Acceptance Criteria",
                "9. Deviation and Change Control",
                "10. Final Report Requirements"
            ],
            depth_guidance="Highly detailed. Must include specific test methods, sample sizes, acceptance criteria, and traceability to design inputs. Regulatory-grade documentation.",
            common_cross_references=["Design Inputs", "Risk Management File", "Design Verification Protocol"]
        ))

        self.register(DocumentType(
            key="computerized_system_validation_protocol",
            display_name="Computerized System Validation Protocol",
            description="Validation protocol for software or computerized systems (CSV/CSA).",
            typical_depth="exhaustive",
            default_section_structure=[
                "1. Introduction and Purpose",
                "2. System Description",
                "3. Validation Strategy",
                "4. Risk Assessment",
                "5. Validation Test Scripts",
                "6. Data Migration (if applicable)",
                "7. Security and Access Controls",
                "8. Backup and Recovery",
                "9. Change Control",
                "10. Final Validation Report"
            ],
            depth_guidance="Very detailed with clear test cases, expected results, and traceability matrix. Must address 21 CFR Part 11 and data integrity where applicable.",
            common_cross_references=["Risk Management File", "Design Validation Protocol"]
        ))

        # === Clinical & Risk ===
        self.register(DocumentType(
            key="clinical_evaluation_plan",
            display_name="Clinical Evaluation Plan",
            description="Plan for clinical evaluation of a medical device.",
            typical_depth="exhaustive",
            default_section_structure=[
                "1. Purpose and Scope",
                "2. Device Description and Intended Use",
                "3. Clinical Evaluation Strategy",
                "4. Identification of Clinical Data",
                "5. Appraisal of Clinical Data",
                "6. Analysis of Clinical Data",
                "7. Conclusions",
                "8. Post-Market Clinical Follow-up Plan"
            ],
            depth_guidance="Comprehensive and well-referenced. Must demonstrate safety and performance with clinical evidence.",
            common_cross_references=["Clinical Evaluation Report", "Risk Management File", "Device Description"]
        ))

        self.register(DocumentType(
            key="risk_management_file",
            display_name="Risk Management File / Hazard Analysis",
            description="Risk management documentation (often includes FMECA or Hazard Analysis).",
            typical_depth="exhaustive",
            default_section_structure=[
                "1. Introduction and Scope",
                "2. Risk Management Process",
                "3. Hazard Identification",
                "4. Risk Estimation",
                "5. Risk Evaluation",
                "6. Risk Control Measures",
                "7. Residual Risk Evaluation",
                "8. Risk-Benefit Analysis",
                "9. Production and Post-Production Monitoring"
            ],
            depth_guidance="Highly detailed with clear risk scoring, control measures, and traceability to design controls and clinical evaluation.",
            common_cross_references=["Design Validation Protocol", "Clinical Evaluation Plan", "FMECA"]
        ))

        # === Cybersecurity & Device Description ===
        self.register(DocumentType(
            key="cybersecurity_plan",
            display_name="Cybersecurity Plan",
            description="Plan addressing cybersecurity risks for medical devices (especially SaMD and connected devices).",
            typical_depth="exhaustive",
            default_section_structure=[
                "1. Purpose and Scope",
                "2. Device Description and Connectivity",
                "3. Threat and Vulnerability Analysis",
                "4. Risk Assessment",
                "5. Cybersecurity Controls",
                "6. Security Testing Strategy",
                "7. Incident Response and Monitoring",
                "8. Labeling and User Information"
            ],
            depth_guidance="Detailed threat modeling and control implementation. Must align with FDA cybersecurity guidance and IEC 81001-5-1.",
            common_cross_references=["Risk Management File", "Design Validation Protocol"]
        ))

        self.register(DocumentType(
            key="device_description_samd",
            display_name="Device Description – SaMD",
            description="Software as a Medical Device description document.",
            typical_depth="standard",
            default_section_structure=[
                "1. Device Name and Version",
                "2. Intended Use / Indications for Use",
                "3. User Profile and Environment",
                "4. Software Description and Architecture",
                "5. Inputs, Outputs, and Algorithms",
                "6. Cybersecurity and Data Privacy",
                "7. Labeling and Instructions for Use"
            ],
            depth_guidance="Clear, structured, and technically accurate. Focus on functionality and clinical context rather than exhaustive implementation details.",
            common_cross_references=["Cybersecurity Plan", "Clinical Evaluation Plan"]
        ))

        # === Quality System ===
        self.register(DocumentType(
            key="capa_procedure",
            display_name="CAPA Procedure",
            description="Corrective and Preventive Action procedure.",
            typical_depth="standard",
            default_section_structure=[
                "1. Purpose",
                "2. Scope",
                "3. Responsibilities",
                "4. Definitions",
                "5. CAPA Process Flow",
                "6. Investigation and Root Cause Analysis",
                "7. Corrective and Preventive Actions",
                "8. Effectiveness Verification",
                "9. Documentation and Records"
            ],
            depth_guidance="Clear process description with decision points and record requirements.",
            common_cross_references=["Complaint Handling Procedure", "Nonconformance Procedure"]
        ))

    def register(self, doc_type: DocumentType):
        self._types[doc_type.key] = doc_type

    def get(self, key: str) -> Optional[DocumentType]:
        return self._types.get(key)

    def list_all(self) -> list[DocumentType]:
        return list(self._types.values())

    def get_keys(self) -> list[str]:
        return list(self._types.keys())


# Singleton instance for easy access
document_type_registry = DocumentTypeRegistry()
