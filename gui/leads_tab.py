from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget, QTableWidgetItem, QCheckBox, QMessageBox
from PyQt6.QtCore import Qt
import os
import json
import requests
import logging
import re
from PyQt6.QtGui import QColor

# Setup logging (centralized in main.py)
logger = logging.getLogger(__name__)
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import QHeaderView
from datetime import datetime

def robust_json_parse_array(response_text, logger=None):
    """
    Robust JSON parsing for arrays that handles various API response formats.
    
    Args:
        response_text: Raw response text from API
        logger: Optional logger for debug messages
    
    Returns:
        tuple: (parsed_json_array, success_flag)
    """
    if logger is None:
        logger = print  # Fallback to print for debug messages
    
    # Step 1: Try direct JSON parsing first
    try:
        clean_response = response_text.strip()
        data = json.loads(clean_response)
        if isinstance(data, list):
            logger(f"Direct JSON array parsing successful")
            return data, True
    except json.JSONDecodeError:
        logger(f"Direct JSON array parsing failed, attempting extraction...")
    
    # Step 2: Try extracting JSON from markdown code blocks
    try:
        # Look for ```json...``` blocks
        json_pattern = r'```(?:json)?\s*(\[.*?\])\s*```'
        match = re.search(json_pattern, response_text, re.DOTALL | re.IGNORECASE)
        if match:
            json_str = match.group(1).strip()
            data = json.loads(json_str)
            if isinstance(data, list):
                logger(f"JSON array extraction from code block successful")
                return data, True
    except (json.JSONDecodeError, AttributeError):
        logger(f"Code block array extraction failed")
    
    # Step 3: Try regex extraction of JSON array
    try:
        # Look for first complete JSON array
        json_pattern = r'\[[^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*\]'
        match = re.search(json_pattern, response_text, re.DOTALL)
        if match:
            json_str = match.group(0).strip()
            data = json.loads(json_str)
            if isinstance(data, list):
                logger(f"Regex JSON array extraction successful")
                return data, True
    except (json.JSONDecodeError, AttributeError):
        logger(f"Regex array extraction failed")
    
    # Step 4: Try finding array boundaries manually
    try:
        start_idx = response_text.find('[')
        end_idx = response_text.rfind(']')
        
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            json_str = response_text[start_idx:end_idx + 1].strip()
            
            # Clean up common issues
            json_str = json_str.replace('```json', '').replace('```', '')
            json_str = re.sub(r',\s*]', ']', json_str)  # Remove trailing commas
            json_str = re.sub(r'\s+', ' ', json_str)   # Normalize whitespace
            
            data = json.loads(json_str)
            if isinstance(data, list):
                logger(f"Manual array extraction successful")
                return data, True
    except (json.JSONDecodeError, AttributeError):
        logger(f"Manual array extraction failed")
    
    logger(f"All JSON array parsing attempts failed")
    return None, False

class LeadsTab(QWidget):
    def __init__(self, chat_handler, data_dir, parent=None):
        super().__init__()
        self.chat_handler = chat_handler
        self.data_dir = data_dir
        self.parent = parent
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)
        
        leads_button_layout = QHBoxLayout()
        self.settingsButton = QPushButton("Settings", self)
        if self.parent and hasattr(self.parent, 'open_settings'):
            self.settingsButton.clicked.connect(self.parent.open_settings)
        else:
            self.settingsButton.clicked.connect(self.open_settings)  # Fallback or define if needed
        self.settingsButton.setToolTip("Open application settings (Ctrl+,)")
        leads_button_layout.addWidget(self.settingsButton)
        
        self.runSearchButton = QPushButton("Run Search", self)
        self.runSearchButton.clicked.connect(self.search_leads)
        self.runSearchButton.setToolTip("Search for new leads (F5)")
        leads_button_layout.addWidget(self.runSearchButton)
        
        layout.addLayout(leads_button_layout)
        
        # Configure the leads table
        self.leadsTable = QTableWidget(0, 8)
        self.leadsTable.setHorizontalHeaderLabels([
            "Name", "Company", "Title", "Contacted", "Contact Date", "Message", "Delete", "Rationale"
        ])
        
        # Set column widths and behavior
        self.leadsTable.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.leadsTable.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.leadsTable.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.leadsTable.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.leadsTable.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.leadsTable.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self.leadsTable.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        self.leadsTable.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
        
        self.leadsTable.setColumnWidth(3, 80)
        self.leadsTable.setColumnWidth(4, 100)
        self.leadsTable.setColumnWidth(5, 120)
        self.leadsTable.setColumnWidth(6, 90)
        
        self.leadsTable.setWordWrap(True)
        layout.addWidget(self.leadsTable)
        
        # Load existing leads
        leads_file = os.path.join(self.data_dir, 'leads.json')
        if os.path.exists(leads_file):
            try:
                with open(leads_file, 'r') as f:
                    leads = json.load(f)
                self.update_leads_table(leads)
                logger.info(f"Loaded {len(leads)} existing leads")
            except Exception as e:
                logger.error(f"Error loading leads: {e}")

    def search_leads(self):
        """Run Grok API search for leads based on system message."""
        try:
            # Load system message from config
            config_path = 'C:/Users/adamo/Dropbox/_Consulting/NaviSsurance/config/lead_gen_config.json'
            if not os.path.exists(config_path):
                logger.error("Lead gen config not found.")
                return
            with open(config_path, 'r') as f:
                config = json.load(f)
            user_system_message = config.get('system_message', '')
            
            if not user_system_message:
                user_system_message = "You are a lead generation assistant for a medical device regulatory consulting firm. Focus on companies in the AI SaMD and/or IVD/LDT space."

            system_message = f"""{user_system_message}

IMPORTANT: When processing search results:
1. Verify each company's current status and leadership team
2. Include a clear rationale for why each lead is relevant
3. Generate a personalized LinkedIn message for each lead based on your research
4. Return results as a JSON array with the following fields for each lead:
   - name: Full name of the key decision maker
   - company: Company name
   - title: Their current title
   - rationale: Why this person/company is a good lead
   - linkedin_url: Their LinkedIn profile URL (if found)
   - message: A personalized LinkedIn message referencing their specific regulatory needs and how NaviSure can help
Only include leads that have been verified through the search results.
"""

            from core.grok_client import grok_completion
            response_content = grok_completion(
                system_message, user_system_message,
                model="grok-4-latest"
            )
            if not response_content:
                logger.error("Grok API returned no content (check XAI_API_KEY or GROK_API_KEY).")
                return

            logger.info("Grok API Response:")
            logger.info(f"Response content: {response_content}")

            response_file = os.path.join(self.data_dir, 'grok_response.txt')
            with open(response_file, 'w', encoding='utf-8') as f:
                f.write("Response content:\n")
                f.write(response_content + "\n")
            logger.info(f"Raw response written to {response_file}")

            # Use robust JSON parsing for leads array
            new_leads, success = robust_json_parse_array(response_content, logger)
            
            if success and new_leads:
                logger.info(f"Parsed leads: {new_leads}")

                if isinstance(new_leads, list):
                    logger.info(f"Successfully parsed JSON array with {len(new_leads)} leads")

                    leads_file = os.path.join(self.data_dir, 'leads.json')
                    existing_leads = []
                    if os.path.exists(leads_file):
                        with open(leads_file, 'r') as f:
                            existing_leads = json.load(f)

                    existing_identifiers = {(lead['name'], lead['company']) for lead in existing_leads}

                    for lead in new_leads:
                        if not all(k in lead for k in ['name', 'company', 'title', 'rationale', 'message']):
                            logger.warning(f"Skipping lead with missing required fields: {lead}")
                            continue
                        lead['contacted'] = False
                        lead['contact_date'] = None
                        lead['linkedin_url'] = lead.get('linkedin_url', '')
                        
                        if (lead['name'], lead['company']) not in existing_identifiers:
                            existing_leads.insert(0, lead)
                            existing_identifiers.add((lead['name'], lead['company']))
                            logger.info(f"Added new lead: {lead['name']} from {lead['company']}")

                    with open(leads_file, 'w') as f:
                        json.dump(existing_leads, f, indent=2)

                    self.update_leads_table(existing_leads)
                    logger.info(f"Successfully loaded {len(new_leads)} new leads")
                    return
            else:
                logger.error("No JSON array found in response")
                logger.error(f"Raw response: {response_content[:500]}...")  # Truncate for logging
        except Exception as e:
            logger.error(f"Search leads error: {e}")
            QMessageBox.warning(self, "API Error", "The Grok API is currently experiencing issues. Please try again in a few minutes.")

    def update_leads_table(self, leads):
        self.leadsTable.setRowCount(len(leads))
        for row, lead in enumerate(leads):
            self.leadsTable.setRowHeight(row, 40)
            
            name_item = QTableWidgetItem(lead.get('name', ''))
            if lead.get('linkedin_url'):
                name_item.setData(Qt.ItemDataRole.UserRole, lead['linkedin_url'])
                name_item.setData(Qt.ItemDataRole.UserRole + 1, "linkedin")
                name_item.setForeground(QColor("#0077B5"))
            self.leadsTable.setItem(row, 0, name_item)
            
            self.leadsTable.setItem(row, 1, QTableWidgetItem(lead.get('company', '')))
            self.leadsTable.setItem(row, 2, QTableWidgetItem(lead.get('title', '')))
            
            contacted_checkbox = QCheckBox()
            contacted_checkbox.setChecked(lead.get('contacted', False))
            contacted_checkbox.stateChanged.connect(lambda state, r=row: self.toggle_contacted(r, state == Qt.CheckState.Checked.value))
            self.leadsTable.setCellWidget(row, 3, contacted_checkbox)
            
            contact_date = QTableWidgetItem(lead.get('contact_date', ''))
            self.leadsTable.setItem(row, 4, contact_date)
            
            message_btn = QPushButton("View Message")
            message_btn.clicked.connect(lambda _, msg=lead.get('message', ''): self.show_message_dialog(msg))
            self.leadsTable.setCellWidget(row, 5, message_btn)
            
            delete_btn = QPushButton("Delete")
            delete_btn.clicked.connect(lambda _, r=row: self.delete_lead(r))
            self.leadsTable.setCellWidget(row, 6, delete_btn)
            
            rationale_item = QTableWidgetItem(lead.get('rationale', ''))
            rationale_item.setToolTip(lead.get('rationale', ''))
            self.leadsTable.setItem(row, 7, rationale_item)
        
        self.leadsTable.cellClicked.connect(self.on_cell_clicked)

    def on_cell_clicked(self, row, column):
        if column == 0:
            item = self.leadsTable.item(row, column)
            url = item.data(Qt.ItemDataRole.UserRole)
            if url:
                QDesktopServices.openUrl(QUrl(url))

    def toggle_contacted(self, row, checked):
        name = self.leadsTable.item(row, 0).text()
        company = self.leadsTable.item(row, 1).text()
        
        leads_file = os.path.join(self.data_dir, 'leads.json')
        if os.path.exists(leads_file):
            with open(leads_file, 'r') as f:
                leads = json.load(f)
            
            for lead in leads:
                if lead['name'] == name and lead['company'] == company:
                    lead['contacted'] = checked
                    lead['contact_date'] = datetime.now().strftime("%Y-%m-%d") if checked else None
                    break
            
            with open(leads_file, 'w') as f:
                json.dump(leads, f, indent=2)

    def show_message_dialog(self, message):
        msg = QMessageBox(self)
        msg.setWindowTitle("LinkedIn Message")
        msg.setText(message)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Copy)
        msg.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        msg.exec()

    def delete_lead(self, row):
        name = self.leadsTable.item(row, 0).text()
        company = self.leadsTable.item(row, 1).text()
        
        reply = QMessageBox.question(self, 'Confirm Delete', f"Are you sure you want to delete {name} from {company}?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            leads_file = os.path.join(self.data_dir, 'leads.json')
            if os.path.exists(leads_file):
                with open(leads_file, 'r') as f:
                    leads = json.load(f)
                
                leads = [lead for lead in leads if not (lead['name'] == name and lead['company'] == company)]
                
                with open(leads_file, 'w') as f:
                    json.dump(leads, f, indent=2)
                
                self.update_leads_table(leads)
