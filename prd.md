Software Requirements Specification (SRS) 

AI-Enabled ERP Web Application (Phase 1 MVP) 

Version: 1.0 | Phase: MVP / Phase 1 | Project Name: ERP Copilot Platform | Date: September 2026 

Author: Vikas Kushwaha 

──────────────────────────────────────── 

 

1. Introduction 

1.1 Purpose 

The purpose of this project is to develop a modern ERP web application that simulates integration with SAP and Infor LN through mock connectors and provides AI-powered business interactions through MCP (Model Context Protocol). 

The application will support procurement and supplier management workflows and provide a clean, responsive user interface for buyers and suppliers. 

The platform is designed to be ERP-agnostic, allowing future replacement of mock connectors with actual SAP S/4HANA or Infor LN integrations. 

 

1.2 Objectives 

The solution should: 

Provide a modern ERP web experience. 

Simulate SAP and Infor LN systems through mock adapters. 

Support Buyers and Suppliers. 

Implement secure JWT-based authentication. 

Expose REST APIs. 

Expose MCP tools through FastMCP. 

Support AI interactions through OpenAPI-compatible MCP endpoints. 

Send transactional emails through Mailpit. 

Store application data in SQLite3. 

Maintain clean architecture for future ERP integrations. 

 

2. Scope 

2.1 Included in Phase 1 

User Management 

User Registration 

User Login 

JWT Authentication 

Role-Based Access Control 

Buyer Portal 

Dashboard 

View Suppliers 

Create Purchase Orders 

Track Purchase Orders 

Inventory View 

Supplier Portal 

Dashboard 

View Assigned Purchase Orders 

Update Delivery Status 

Manage Supplier Profile 

Procurement 

Create Purchase Orders 

Approve Purchase Orders 

Update PO Status 

View PO History 

Inventory 

Inventory Listing 

Stock Availability 

Item Search 

MCP Integration 

FastMCP Server 

OpenAPI Support 

MCP Tools 

AI-ready Architecture 

Notifications 

Email Notifications 

Mailpit Integration 

 

3. Users and Roles 

3.1 Buyer 

Responsible for procurement activities. 

Permissions: 

Login 

View Dashboard 

View Suppliers 

Create Purchase Orders 

View Inventory 

Track Orders 

 

3.2 Supplier 

Responsible for fulfilling purchase orders. 

Permissions: 

Login 

View Assigned Orders 

Update Delivery Status 

Manage Profile 

 

3.3 Administrator (Future) 

Not included in MVP but architecture should support: 

User Management 

ERP Configuration 

MCP Configuration 

 

4. Technology Stack 

Frontend 

Framework 

Next.js 15 

React 

TypeScript 

UI 

Tailwind CSS 

ShadCN UI 

Features 

Responsive Layout 

Light/Dark Mode 

Dashboard Components 

Data Tables 

Charts 

 

Backend 

API Framework 

FastAPI 

Language 

Python 3.12+ 

API Protocol 

REST API 

 

Database 

Database Engine 

SQLite3 

Purpose: 

User Data 

Supplier Data 

Inventory 

Purchase Orders 

Notifications 

Audit Logs 

 

Authentication 

Method 

JWT Authentication 

Features 

Access Token 

Token Expiration 

Role Validation 

API Authorization 

 

AI/MCP Layer 

MCP Framework 

FastMCP 

Protocol 

Model Context Protocol 

OpenAPI Support 

Required 

The MCP Server shall expose: 

Tool Definitions 

Tool Discovery 

OpenAPI Schema 

 

Email 

Local SMTP 

Mailpit 

Purpose: 

Testing Email Flows 

Purchase Order Notifications 

Supplier Alerts 

System Emails 

 

5. System Architecture 

Architecture overview: The system follows a layered web architecture with a Next.js frontend, JWT-secured FastAPI backend, SQLite database, Mailpit email service, FastMCP server, and mock ERP connectors for SAP and Infor LN. 

Layer 

Component 

Purpose 

Frontend 

Next.js UI 

Provides buyer and supplier user interfaces. 

Authentication 

JWT Authentication 

Secures access to role-based application features. 

Backend 

FastAPI API 

Exposes REST endpoints for ERP workflows. 

Data 

SQLite Database 

Stores users, suppliers, inventory, purchase orders, notifications, and audit data. 

Email 

Mailpit Server 

Captures transactional emails in the local development environment. 

AI/MCP 

FastMCP Server 

Exposes AI-ready ERP tools through MCP. 

ERP Simulation 

Mock SAP and Infor LN Connectors 

Simulates external ERP integrations for Phase 1. 

 

 

6. Functional Requirements 

FR-001 User Registration 

Users shall be able to register as: 

Buyer 

Supplier 

Fields: 

Name 

Email 

Password 

Role 

 

FR-002 User Login 

Users shall authenticate using email and password. 

System shall: 

Validate Credentials 

Generate JWT Token 

Return User Profile 

 

FR-003 Purchase Order Creation 

Buyer shall create Purchase Orders. 

Fields: 

PO Number 

Supplier 

Items 

Quantity 

Unit Price 

Status 

Created Date 

Status: 

Draft 

Pending 

Approved 

Closed 

 

FR-004 Supplier Management 

Buyer shall: 

View Suppliers 

Search Suppliers 

Filter Suppliers 

Supplier shall: 

Update Profile 

View Assigned Orders 

 

FR-005 Inventory Management 

System shall maintain inventory. 

Fields: 

Item Code 

Description 

Stock Quantity 

Warehouse 

Last Updated 

 

FR-006 Dashboard 

Buyer Dashboard: 

Open Orders 

Inventory Count 

Supplier Count 

Recent Activities 

Supplier Dashboard: 

Active Orders 

Pending Deliveries 

Notifications 

 

FR-007 Email Notifications 

System shall send email notifications: 

Events: 

New Purchase Order 

Order Approved 

Order Delivered 

Mailpit shall capture emails locally. 

 

7. MCP Requirements 

MCP Goal 

Allow AI agents to communicate with ERP services through standardized MCP tools. 

 

MCP Tool 1 

Get Inventory 

Tool Name: get_inventory 

Input: {"item_code": "ITEM001"} 

Output: {"item_code": "ITEM001", "stock": 100} 

 

MCP Tool 2 

Search Supplier 

Tool Name: search_supplier 

Input: {"supplier_name": "ABC"} 

 

MCP Tool 3 

Create Purchase Order 

Tool Name: create_purchase_order 

Input: {"supplier_id": 1, "item_code": "ITEM001", "quantity": 100} 

 

MCP Tool 4 

Get Purchase Order 

Tool Name: get_purchase_order 

Input: {"po_number": "PO1001"} 

 

8. Mock ERP Requirements 

Mock SAP Connector 

Endpoints: 

GET /mock/sap/materials 

GET /mock/sap/vendors 

GET /mock/sap/purchase-orders 

POST /mock/sap/purchase-orders 

Purpose: 

Simulate SAP data 

 

Mock Infor LN Connector 

Endpoints: 

GET /mock/infor/items 

GET /mock/infor/suppliers 

GET /mock/infor/orders 

POST /mock/infor/orders 

Purpose: 

Simulate Infor LN data 

 

9. REST API Requirements 

Authentication 

POST /api/auth/register 

POST /api/auth/login 

 

Suppliers 

GET /api/suppliers 

GET /api/suppliers/{id} 

POST /api/suppliers 

PUT /api/suppliers/{id} 

 

Purchase Orders 

GET /api/purchase-orders 

POST /api/purchase-orders 

PUT /api/purchase-orders/{id} 

GET /api/purchase-orders/{id} 

 

Inventory 

GET /api/inventory 

GET /api/inventory/{itemCode} 

 

10. Database Design 

Users 

id 

name 

email 

password_hash 

role 

created_at 

 

Suppliers 

id 

supplier_name 

email 

phone 

address 

created_at 

 

Inventory 

id 

item_code 

description 

stock_quantity 

warehouse 

updated_at 

 

PurchaseOrders 

id 

po_number 

supplier_id 

status 

total_amount 

created_at 

 

PurchaseOrderItems 

id 

po_id 

item_code 

quantity 

unit_price 

 

11. Non-Functional Requirements 

Security 

JWT-based Authentication 

Password Hashing 

API Authorization 

Input Validation 

Role-Based Access Control 

 

Performance 

API Response < 2 Seconds 

Dashboard Load < 3 Seconds 

 

Scalability 

Architecture should support future migration from mock ERP connectors to real SAP S/4HANA and Infor LN integrations without major code changes. 

 

12. Phase 1 Deliverables 

Backend 

FastAPI Application 

JWT Authentication 

SQLite3 Database 

REST APIs 

Mock SAP Connector 

Mock Infor LN Connector 

MCP 

FastMCP Server 

OpenAPI Tool Definitions 

ERP MCP Tools 

Frontend 

Next.js Application 

Buyer Portal 

Supplier Portal 

Dashboard 

Clean Responsive UI 

Infrastructure 

Mailpit 

Local Development Environment 

Docker Compose Setup 

 

13. Deployment Criteria 

The Phase 1 MVP shall be deployed using a containerized setup consisting of three Docker images: one for the frontend, one for the backend, and one for the database. The complete environment shall be started and managed through a single Docker Compose file. 

13.1 Docker Images 

Docker Image 

Component 

Purpose 

Expected Port 

frontend 

Next.js Application 

Serves the buyer and supplier web portals. 

3000 

backend 

FastAPI Application 

Exposes REST APIs, authentication, mock ERP services, and MCP-compatible backend logic. 

8000 

database 

SQLite Database Service / Persistent Volume 

Stores application data including users, suppliers, inventory, purchase orders, notifications, and audit logs. 

Internal only 

 

13.2 Docker Compose Requirements 

The deployment shall include a single docker-compose.yml file. 

Docker Compose shall build or pull the frontend, backend, and database images. 

The frontend service shall depend on the backend service. 

The backend service shall depend on the database service. 

Environment variables shall be defined for API URLs, database path/connection settings, JWT secret, and email/Mailpit configuration. 

Application data shall be persisted using a named volume or mounted storage for the database. 

Services shall run on a shared Docker network to allow internal communication. 

The deployment should support local startup using a single command: docker compose up --build. 

13.3 Deployment Acceptance Criteria 

All three containers start successfully through Docker Compose. 

The frontend is accessible from the configured host port. 

The backend health endpoint responds successfully after startup. 

The backend can read from and write to the database container or mounted database volume. 

The frontend can communicate with the backend API over the Docker network or configured public API URL. 

Database data remains available after container restart when persistence is enabled. 

Logs for all services are accessible through Docker Compose. 

The deployment setup can be reproduced on a clean developer machine with Docker installed. 

14. Success Criteria 

Buyer and Supplier login using JWT 

Create and manage Purchase Orders 

Simulate SAP and Infor LN integrations 

MCP tools operational via FastMCP 

REST APIs fully functional 

Email notifications visible in Mailpit 

Responsive ERP UI 

SQLite3 persistence 

Future-ready architecture for real SAP/Infor LN connectors and AI Copilot integration 

End of Software Requirements Specification 

 