CREATE SCHEMA IF NOT EXISTS genel_bakis;

CREATE SCHEMA IF NOT EXISTS envanter;

CREATE SCHEMA IF NOT EXISTS baglanti;

CREATE SCHEMA IF NOT EXISTS ip_adres_yonetimi;

CREATE SCHEMA IF NOT EXISTS firmware;

CREATE SCHEMA IF NOT EXISTS konfigurasyon;

CREATE SCHEMA IF NOT EXISTS operasyon;

CREATE SCHEMA IF NOT EXISTS yonetim;

CREATE TABLE yonetim.users (
	email VARCHAR(190) NOT NULL, 
	display_name VARCHAR(120) NOT NULL, 
	password_hash TEXT NOT NULL, 
	role VARCHAR(20) NOT NULL, 
	ssh_access BOOLEAN DEFAULT '0' NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_user_role CHECK (role in ('super_admin','admin','operator','viewer')), 
	CONSTRAINT ck_user_super_admin_email CHECK (role <> 'super_admin' OR lower(email) = 'alisan.yildirim@fbu.edu.tr'), 
	UNIQUE (email)
);

CREATE TABLE ip_adres_yonetimi.institutions (
	name VARCHAR(190) NOT NULL, 
	code VARCHAR(20) NOT NULL, 
	lock_version INTEGER DEFAULT '0' NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (code)
);

CREATE TABLE ip_adres_yonetimi.model_images (
	vendor VARCHAR(80) NOT NULL, 
	model VARCHAR(100) NOT NULL, 
	url VARCHAR(500) NOT NULL, 
	source VARCHAR(500) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (vendor, model)
);

CREATE TABLE ip_adres_yonetimi.operating_systems (
	name VARCHAR(190) NOT NULL, 
	description VARCHAR(400) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (name)
);

CREATE TABLE ip_adres_yonetimi.vrfs (
	lock_version INTEGER DEFAULT '0' NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	description VARCHAR(400) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (name)
);

CREATE TABLE ip_adres_yonetimi.ipam_scan_groups (
	name VARCHAR(120) NOT NULL, 
	description VARCHAR(400) NOT NULL, 
	enabled BOOLEAN NOT NULL, 
	frequency VARCHAR(10) NOT NULL, 
	repeat_every INTEGER NOT NULL, 
	timezone VARCHAR(60) NOT NULL, 
	start_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	next_run_at TIMESTAMP WITH TIME ZONE, 
	run_limit INTEGER, 
	run_count INTEGER NOT NULL, 
	generation INTEGER NOT NULL, 
	last_run_at TIMESTAMP WITH TIME ZONE, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_ipam_scan_frequency CHECK (frequency in ('daily','weekly','monthly')), 
	CONSTRAINT ck_ipam_scan_every CHECK (repeat_every >= 1 AND repeat_every <= 365), 
	CONSTRAINT ck_ipam_scan_count CHECK (run_count >= 0 AND (run_limit IS NULL OR run_limit >= 1)), 
	UNIQUE (name)
);

CREATE INDEX ix_ipam_scan_due ON ip_adres_yonetimi.ipam_scan_groups (enabled, next_run_at);

CREATE TABLE yonetim.credentials (
	name VARCHAR(120) NOT NULL, 
	protocol VARCHAR(20) NOT NULL, 
	encrypted_secret TEXT NOT NULL, 
	key_version INTEGER NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_credential_protocol CHECK (protocol in ('snmpv3','snmpv2c','ssh','rest')), 
	UNIQUE (name)
);

CREATE TABLE konfigurasyon.backup_groups (
	name VARCHAR(120) NOT NULL, 
	description VARCHAR(400) NOT NULL, 
	interval_seconds INTEGER NOT NULL, 
	retention_count INTEGER NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_backup_group_interval CHECK (interval_seconds = 0 OR interval_seconds >= 300), 
	CONSTRAINT ck_backup_group_retention CHECK (retention_count >= 0), 
	UNIQUE (name)
);

CREATE TABLE envanter.device_types (
	code VARCHAR(20) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	description VARCHAR(400) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (code), 
	UNIQUE (name)
);

CREATE TABLE ip_adres_yonetimi.dns_servers (
	name VARCHAR(120) NOT NULL, 
	address VARCHAR(45) NOT NULL, 
	port INTEGER NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (name)
);

CREATE TABLE yonetim.integrations (
	name VARCHAR(120) NOT NULL, 
	kind VARCHAR(20) NOT NULL, 
	host VARCHAR(253) NOT NULL, 
	port INTEGER NOT NULL, 
	encrypted_secret TEXT NOT NULL, 
	enabled BOOLEAN NOT NULL, 
	verify_tls BOOLEAN NOT NULL, 
	interval_seconds INTEGER NOT NULL, 
	last_run_at TIMESTAMP WITH TIME ZONE, 
	last_success_at TIMESTAMP WITH TIME ZONE, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_integration_kind CHECK (kind in ('vcenter','windows_dhcp')), 
	CONSTRAINT ck_integration_interval CHECK (interval_seconds = 0 OR interval_seconds >= 60), 
	UNIQUE (name)
);

CREATE TABLE firmware.firmware_groups (
	name VARCHAR(120) NOT NULL, 
	description VARCHAR(400) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (name)
);

CREATE TABLE operasyon.alert_rules (
	name VARCHAR(120) NOT NULL, 
	metric VARCHAR(30) NOT NULL, 
	threshold FLOAT NOT NULL, 
	recovery_threshold FLOAT NOT NULL, 
	duration_seconds INTEGER NOT NULL, 
	severity VARCHAR(20) NOT NULL, 
	enabled BOOLEAN NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_alert_metric CHECK (metric = 'config_change'), 
	CONSTRAINT ck_alert_severity CHECK (severity in ('info','warning','critical'))
);

CREATE TABLE yonetim.system_state (
	key VARCHAR(40) NOT NULL, 
	value VARCHAR(100) NOT NULL, 
	PRIMARY KEY (key)
);

CREATE TABLE ip_adres_yonetimi.vmware_networks (
	source_key VARCHAR(120) NOT NULL, 
	external_key VARCHAR(64) NOT NULL, 
	switch_id VARCHAR(190) NOT NULL, 
	switch_name VARCHAR(190) NOT NULL, 
	standard_switch VARCHAR(190) NOT NULL, 
	portgroup_key VARCHAR(190) NOT NULL, 
	name VARCHAR(190) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_vmware_network UNIQUE (source_key, external_key)
);

CREATE TABLE yonetim.user_avatars (
	user_id VARCHAR(36) NOT NULL, 
	preset_id VARCHAR(40), 
	image BYTEA, 
	version VARCHAR(36) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (user_id), 
	CONSTRAINT ck_user_avatar_source CHECK ((preset_id IS NULL AND image IS NOT NULL) OR (preset_id IS NOT NULL AND image IS NULL)), 
	FOREIGN KEY(user_id) REFERENCES yonetim.users (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE
);

CREATE TABLE yonetim.auth_sessions (
	token_hash VARCHAR(64) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (token_hash), 
	FOREIGN KEY(user_id) REFERENCES yonetim.users (id) DEFERRABLE INITIALLY IMMEDIATE
);

CREATE INDEX ix_yonetim_auth_sessions_expires_at ON yonetim.auth_sessions (expires_at);

CREATE INDEX ix_yonetim_auth_sessions_user_id ON yonetim.auth_sessions (user_id);

CREATE TABLE yonetim.audit_events (
	actor_id VARCHAR(36), 
	action VARCHAR(80) NOT NULL, 
	entity_type VARCHAR(60) NOT NULL, 
	entity_id VARCHAR(36), 
	summary VARCHAR(400) NOT NULL, 
	details JSONB, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(actor_id) REFERENCES yonetim.users (id) DEFERRABLE INITIALLY IMMEDIATE
);

CREATE INDEX ix_audit_events_created_at ON yonetim.audit_events (created_at DESC, id);

CREATE INDEX ix_yonetim_audit_events_actor_id ON yonetim.audit_events (actor_id);

CREATE TABLE ip_adres_yonetimi.sites (
	institution_id VARCHAR(36), 
	parent_id VARCHAR(36), 
	name VARCHAR(120) NOT NULL, 
	code VARCHAR(40) NOT NULL, 
	description VARCHAR(400) NOT NULL, 
	timezone VARCHAR(50) NOT NULL, 
	floor_number VARCHAR(40) DEFAULT '' NOT NULL, 
	department_name VARCHAR(120) DEFAULT '' NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(institution_id) REFERENCES ip_adres_yonetimi.institutions (id) DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(parent_id) REFERENCES ip_adres_yonetimi.sites (id) DEFERRABLE INITIALLY IMMEDIATE, 
	UNIQUE (code)
);

CREATE INDEX ix_ip_adres_yonetimi_sites_parent_id ON ip_adres_yonetimi.sites (parent_id);

CREATE INDEX ix_ip_adres_yonetimi_sites_institution_id ON ip_adres_yonetimi.sites (institution_id);

CREATE TABLE ip_adres_yonetimi.ipam_scan_runs (
	group_id VARCHAR(36) NOT NULL, 
	scheduled_for TIMESTAMP WITH TIME ZONE NOT NULL, 
	generation INTEGER NOT NULL, 
	jobs JSONB NOT NULL, 
	errors JSONB NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_ipam_scan_slot UNIQUE (group_id, generation, scheduled_for), 
	FOREIGN KEY(group_id) REFERENCES ip_adres_yonetimi.ipam_scan_groups (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE
);

CREATE INDEX ix_ip_adres_yonetimi_ipam_scan_runs_group_id ON ip_adres_yonetimi.ipam_scan_runs (group_id);

CREATE TABLE operasyon.jobs (
	kind VARCHAR(20) NOT NULL, 
	target_id VARCHAR(36) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	active_key VARCHAR(100), 
	requested_by VARCHAR(36), 
	attempts INTEGER NOT NULL, 
	progress INTEGER NOT NULL, 
	total INTEGER NOT NULL, 
	result JSONB NOT NULL, 
	error VARCHAR(200) NOT NULL, 
	cancel_requested BOOLEAN NOT NULL, 
	heartbeat_at TIMESTAMP WITH TIME ZONE, 
	available_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	finished_at TIMESTAMP WITH TIME ZONE, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_job_status CHECK (status in ('queued','running','succeeded','partial','failed','cancelled')), 
	UNIQUE (active_key), 
	FOREIGN KEY(requested_by) REFERENCES yonetim.users (id) DEFERRABLE INITIALLY IMMEDIATE
);

CREATE INDEX ix_operasyon_jobs_status ON operasyon.jobs (status);

CREATE INDEX ix_operasyon_jobs_target_id ON operasyon.jobs (target_id);

CREATE INDEX ix_operasyon_jobs_available_at ON operasyon.jobs (available_at);

CREATE TABLE firmware.firmware_images (
	name VARCHAR(120) NOT NULL, 
	family VARCHAR(20) NOT NULL, 
	version VARCHAR(120) NOT NULL, 
	models JSONB NOT NULL, 
	original_name VARCHAR(160) NOT NULL, 
	size_bytes BIGINT NOT NULL, 
	sha256 VARCHAR(64) NOT NULL, 
	expected_sha256 VARCHAR(64) NOT NULL, 
	notes TEXT NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	uploaded_by VARCHAR(36), 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_fw_image_family CHECK (family in ('aos_s_54xx','aos_s_29xx','cx6100','hp1950')), 
	CONSTRAINT ck_fw_image_status CHECK (status in ('uploading','ready')), 
	CONSTRAINT ck_fw_image_size CHECK (size_bytes >= 0), 
	FOREIGN KEY(uploaded_by) REFERENCES yonetim.users (id) DEFERRABLE INITIALLY IMMEDIATE
);

CREATE INDEX ix_firmware_firmware_images_status ON firmware.firmware_images (status);

CREATE INDEX ix_firmware_firmware_images_family ON firmware.firmware_images (family);

CREATE TABLE firmware.firmware_plans (
	name VARCHAR(120) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	mode VARCHAR(20) NOT NULL, 
	steps JSONB NOT NULL, 
	concurrency INTEGER NOT NULL, 
	available_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	requested_by VARCHAR(36), 
	cancel_requested BOOLEAN NOT NULL, 
	force_stop_requested BOOLEAN NOT NULL, 
	deleted_at TIMESTAMP WITH TIME ZONE, 
	finished_at TIMESTAMP WITH TIME ZONE, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_fw_plan_concurrency CHECK (concurrency between 1 and 10), 
	CONSTRAINT ck_fw_plan_mode CHECK (mode in ('check','stage','upgrade','activate','verify')), 
	CONSTRAINT ck_fw_plan_status CHECK (status in ('draft','queued','running','paused','ready','succeeded','cancelled')), 
	FOREIGN KEY(requested_by) REFERENCES yonetim.users (id) DEFERRABLE INITIALLY IMMEDIATE
);

CREATE INDEX ix_firmware_firmware_plans_available_at ON firmware.firmware_plans (available_at);

CREATE INDEX ix_firmware_firmware_plans_status ON firmware.firmware_plans (status);

CREATE INDEX ix_fw_plan_history_order ON firmware.firmware_plans (created_at, id);

CREATE TABLE yonetim.user_workspaces (
	user_id VARCHAR(36) NOT NULL, 
	preferences JSONB NOT NULL, 
	encrypted_commands TEXT, 
	PRIMARY KEY (user_id), 
	FOREIGN KEY(user_id) REFERENCES yonetim.users (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE
);

CREATE TABLE yonetim.user_ssh_profiles (
	owner_id VARCHAR(36) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	encrypted_ssh TEXT NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_user_ssh_profile_name UNIQUE (owner_id, name), 
	CONSTRAINT uq_user_ssh_profile_owner UNIQUE (id, owner_id), 
	FOREIGN KEY(owner_id) REFERENCES yonetim.users (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE
);

CREATE TABLE ip_adres_yonetimi.dhcp_bindings (
	integration_id VARCHAR(36), 
	source_key VARCHAR(120) NOT NULL, 
	address VARCHAR(45) NOT NULL, 
	mac_address VARCHAR(17) NOT NULL, 
	hostname VARCHAR(190) NOT NULL, 
	reserved BOOLEAN NOT NULL, 
	lease_state VARCHAR(40) NOT NULL, 
	present BOOLEAN NOT NULL, 
	observed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_dhcp_fact UNIQUE (source_key, address, mac_address), 
	FOREIGN KEY(integration_id) REFERENCES yonetim.integrations (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE
);

CREATE INDEX ix_dhcp_mac ON ip_adres_yonetimi.dhcp_bindings (mac_address, source_key);

CREATE TABLE ip_adres_yonetimi.vmware_hosts (
	integration_id VARCHAR(36), 
	source_key VARCHAR(120) NOT NULL, 
	external_id VARCHAR(190) NOT NULL, 
	hostname VARCHAR(190) NOT NULL, 
	uuid VARCHAR(190) NOT NULL, 
	operating_system VARCHAR(190) NOT NULL, 
	power_state VARCHAR(40) NOT NULL, 
	observed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_vmware_host UNIQUE (source_key, external_id), 
	FOREIGN KEY(integration_id) REFERENCES yonetim.integrations (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE
);

CREATE TABLE ip_adres_yonetimi.cabinets (
	sub_site_id VARCHAR(36), 
	units INTEGER DEFAULT '42' NOT NULL, 
	lock_version INTEGER DEFAULT '0' NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	site_id VARCHAR(36), 
	description VARCHAR(400) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_cabinet_units CHECK (units >= 1 AND units <= 60), 
	CONSTRAINT uq_cabinet_room_number UNIQUE (sub_site_id, name), 
	FOREIGN KEY(sub_site_id) REFERENCES ip_adres_yonetimi.sites (id) DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(site_id) REFERENCES ip_adres_yonetimi.sites (id) DEFERRABLE INITIALLY IMMEDIATE
);

CREATE INDEX ix_ip_adres_yonetimi_cabinets_site_id ON ip_adres_yonetimi.cabinets (site_id);

CREATE INDEX ix_ip_adres_yonetimi_cabinets_sub_site_id ON ip_adres_yonetimi.cabinets (sub_site_id);

CREATE TABLE ip_adres_yonetimi.vlans (
	name VARCHAR(120) NOT NULL, 
	domain VARCHAR(80) NOT NULL, 
	vid INTEGER NOT NULL, 
	institution_id VARCHAR(36), 
	cidr VARCHAR(49), 
	vrf_id VARCHAR(36), 
	site_id VARCHAR(36), 
	description VARCHAR(400) NOT NULL, 
	dns_server_id VARCHAR(36), 
	warning_threshold INTEGER DEFAULT '80' NOT NULL, 
	ping_enabled BOOLEAN DEFAULT '1' NOT NULL, 
	ping_interval INTEGER DEFAULT '30' NOT NULL, 
	discovery_enabled BOOLEAN DEFAULT '0' NOT NULL, 
	discovery_interval INTEGER DEFAULT '3600' NOT NULL, 
	last_ping_at TIMESTAMP WITH TIME ZONE, 
	last_discovery_at TIMESTAMP WITH TIME ZONE, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (domain, vid), 
	UNIQUE (vrf_id, cidr), 
	CONSTRAINT ck_vlan_threshold CHECK (warning_threshold >= 1 AND warning_threshold <= 100), 
	CONSTRAINT ck_vlan_intervals CHECK (ping_interval >= 10 AND discovery_interval >= 60), 
	CONSTRAINT ck_vlan_vid CHECK (vid >= 1 AND vid <= 4094), 
	FOREIGN KEY(institution_id) REFERENCES ip_adres_yonetimi.institutions (id) DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(vrf_id) REFERENCES ip_adres_yonetimi.vrfs (id) DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(site_id) REFERENCES ip_adres_yonetimi.sites (id) DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(dns_server_id) REFERENCES ip_adres_yonetimi.dns_servers (id) DEFERRABLE INITIALLY IMMEDIATE
);

CREATE INDEX ix_ip_adres_yonetimi_vlans_dns_server_id ON ip_adres_yonetimi.vlans (dns_server_id);

CREATE INDEX ix_ip_adres_yonetimi_vlans_vrf_id ON ip_adres_yonetimi.vlans (vrf_id);

CREATE INDEX ix_ip_adres_yonetimi_vlans_institution_id ON ip_adres_yonetimi.vlans (institution_id);

CREATE INDEX ix_ip_adres_yonetimi_vlans_site_id ON ip_adres_yonetimi.vlans (site_id);

CREATE TABLE envanter.discovery_scopes (
	vlan_vid INTEGER, 
	institution_id VARCHAR(36), 
	name VARCHAR(120) NOT NULL, 
	cidr VARCHAR(49) NOT NULL, 
	vrf_id VARCHAR(36) NOT NULL, 
	credential_id VARCHAR(36) NOT NULL, 
	site_id VARCHAR(36), 
	exclusions JSONB NOT NULL, 
	seeds JSONB NOT NULL, 
	enabled BOOLEAN NOT NULL, 
	interval_seconds INTEGER NOT NULL, 
	last_run_at TIMESTAMP WITH TIME ZONE, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_scope_interval CHECK (interval_seconds = 0 OR interval_seconds >= 300), 
	FOREIGN KEY(institution_id) REFERENCES ip_adres_yonetimi.institutions (id) DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(vrf_id) REFERENCES ip_adres_yonetimi.vrfs (id) DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(credential_id) REFERENCES yonetim.credentials (id) DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(site_id) REFERENCES ip_adres_yonetimi.sites (id) DEFERRABLE INITIALLY IMMEDIATE
);

CREATE INDEX ix_envanter_discovery_scopes_vrf_id ON envanter.discovery_scopes (vrf_id);

CREATE INDEX ix_envanter_discovery_scopes_credential_id ON envanter.discovery_scopes (credential_id);

CREATE INDEX ix_envanter_discovery_scopes_site_id ON envanter.discovery_scopes (site_id);

CREATE INDEX ix_envanter_discovery_scopes_institution_id ON envanter.discovery_scopes (institution_id);

CREATE TABLE yonetim.access_groups (
	owner_id VARCHAR(36) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	description VARCHAR(400) NOT NULL, 
	ssh_profile_id VARCHAR(36), 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_access_group_owner_name UNIQUE (owner_id, name), 
	CONSTRAINT uq_access_group_identity_owner UNIQUE (id, owner_id), 
	CONSTRAINT fk_access_group_ssh_owner FOREIGN KEY(ssh_profile_id, owner_id) REFERENCES yonetim.user_ssh_profiles (id, owner_id) DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(owner_id) REFERENCES yonetim.users (id) DEFERRABLE INITIALLY IMMEDIATE
);

CREATE INDEX ix_access_group_ssh_profile_owner ON yonetim.access_groups (ssh_profile_id, owner_id);

CREATE INDEX ix_yonetim_access_groups_owner_id ON yonetim.access_groups (owner_id);

CREATE TABLE ip_adres_yonetimi.vmware_vms (
	integration_id VARCHAR(36), 
	source_key VARCHAR(120) NOT NULL, 
	external_id VARCHAR(190) NOT NULL, 
	host_id VARCHAR(36), 
	hostname VARCHAR(190) NOT NULL, 
	operating_system VARCHAR(190) NOT NULL, 
	power_state VARCHAR(40) NOT NULL, 
	observed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_vmware_vm UNIQUE (source_key, external_id), 
	FOREIGN KEY(integration_id) REFERENCES yonetim.integrations (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(host_id) REFERENCES ip_adres_yonetimi.vmware_hosts (id) ON DELETE SET NULL DEFERRABLE INITIALLY IMMEDIATE
);

CREATE INDEX ix_ip_adres_yonetimi_vmware_vms_host_id ON ip_adres_yonetimi.vmware_vms (host_id);

CREATE TABLE ip_adres_yonetimi.vmware_physical_nics (
	host_id VARCHAR(36) NOT NULL, 
	device VARCHAR(120) NOT NULL, 
	mac_address VARCHAR(17) NOT NULL, 
	link_up BOOLEAN NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_vmware_pnic UNIQUE (host_id, device), 
	FOREIGN KEY(host_id) REFERENCES ip_adres_yonetimi.vmware_hosts (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE
);

CREATE INDEX ix_ip_adres_yonetimi_vmware_physical_nics_host_id ON ip_adres_yonetimi.vmware_physical_nics (host_id);

CREATE TABLE ip_adres_yonetimi.rack_accessories (
	cabinet_id VARCHAR(36) NOT NULL, 
	kind VARCHAR(30) NOT NULL, 
	start_unit INTEGER NOT NULL, 
	units INTEGER NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_rack_accessory_kind CHECK (kind = 'brush_organizer'), 
	CONSTRAINT ck_rack_accessory_position CHECK (start_unit >= 1 AND units >= 1 AND start_unit + units - 1 <= 60), 
	FOREIGN KEY(cabinet_id) REFERENCES ip_adres_yonetimi.cabinets (id) DEFERRABLE INITIALLY IMMEDIATE
);

CREATE INDEX ix_ip_adres_yonetimi_rack_accessories_cabinet_id ON ip_adres_yonetimi.rack_accessories (cabinet_id);

CREATE TABLE ip_adres_yonetimi.patch_panels (
	cabinet_id VARCHAR(36) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	kind VARCHAR(20) NOT NULL, 
	start_unit INTEGER NOT NULL, 
	units INTEGER NOT NULL, 
	port_count INTEGER NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_patch_panel_name UNIQUE (cabinet_id, name), 
	CONSTRAINT ck_patch_panel_kind CHECK (kind in ('cat','fiber')), 
	CONSTRAINT ck_patch_panel_position CHECK (start_unit >= 1 AND units >= 1 AND start_unit + units - 1 <= 60), 
	CONSTRAINT ck_patch_panel_count CHECK (port_count >= 1 AND port_count <= 288), 
	FOREIGN KEY(cabinet_id) REFERENCES ip_adres_yonetimi.cabinets (id) DEFERRABLE INITIALLY IMMEDIATE
);

CREATE INDEX ix_ip_adres_yonetimi_patch_panels_cabinet_id ON ip_adres_yonetimi.patch_panels (cabinet_id);

CREATE TABLE ip_adres_yonetimi.ipam_scan_members (
	group_id VARCHAR(36) NOT NULL, 
	vlan_id VARCHAR(36) NOT NULL, 
	PRIMARY KEY (group_id, vlan_id), 
	FOREIGN KEY(group_id) REFERENCES ip_adres_yonetimi.ipam_scan_groups (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE, 
	UNIQUE (vlan_id), 
	FOREIGN KEY(vlan_id) REFERENCES ip_adres_yonetimi.vlans (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE
);

CREATE TABLE envanter.devices (
	discovery_scope_id VARCHAR(36), 
	name VARCHAR(120) NOT NULL, 
	management_ip VARCHAR(45) NOT NULL, 
	vrf_id VARCHAR(36) NOT NULL, 
	site_id VARCHAR(36), 
	vendor VARCHAR(80) NOT NULL, 
	model VARCHAR(100) NOT NULL, 
	manual_identity_fields JSONB DEFAULT '[]' NOT NULL, 
	software_version VARCHAR(120) DEFAULT '' NOT NULL, 
	kind VARCHAR(20) NOT NULL, 
	lifecycle_status VARCHAR(20) NOT NULL, 
	reachability VARCHAR(20) NOT NULL, 
	adapter VARCHAR(20) NOT NULL, 
	snmp_credential_id VARCHAR(36), 
	config_credential_id VARCHAR(36), 
	snmp_port INTEGER NOT NULL, 
	config_port INTEGER NOT NULL, 
	ssh_trust_host_key BOOLEAN DEFAULT '0' NOT NULL, 
	is_gateway BOOLEAN DEFAULT '0' NOT NULL, 
	config_path VARCHAR(200) NOT NULL, 
	identity_path VARCHAR(200) DEFAULT '/api/system' NOT NULL, 
	backup_interval INTEGER NOT NULL, 
	last_seen_at TIMESTAMP WITH TIME ZONE, 
	archived BOOLEAN DEFAULT '0' NOT NULL, 
	backup_group_id VARCHAR(36), 
	backup_retention INTEGER DEFAULT '0' NOT NULL, 
	last_backup_at TIMESTAMP WITH TIME ZONE, 
	base_snapshot_id VARCHAR(36), 
	approved_config_hash VARCHAR(64) DEFAULT '' NOT NULL, 
	config_approved_at TIMESTAMP WITH TIME ZONE, 
	config_approved_by VARCHAR(36), 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (vrf_id, management_ip), 
	CONSTRAINT ck_device_status CHECK (lifecycle_status in ('planned','active','maintenance','retired')), 
	CONSTRAINT ck_device_interval CHECK (backup_interval >= 0), 
	FOREIGN KEY(discovery_scope_id) REFERENCES envanter.discovery_scopes (id) ON DELETE SET NULL DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(vrf_id) REFERENCES ip_adres_yonetimi.vrfs (id) DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(site_id) REFERENCES ip_adres_yonetimi.sites (id) DEFERRABLE INITIALLY IMMEDIATE, 
	CONSTRAINT fk_device_type FOREIGN KEY(kind) REFERENCES envanter.device_types (code) DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(snmp_credential_id) REFERENCES yonetim.credentials (id) DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(config_credential_id) REFERENCES yonetim.credentials (id) DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(backup_group_id) REFERENCES konfigurasyon.backup_groups (id) DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(config_approved_by) REFERENCES yonetim.users (id) DEFERRABLE INITIALLY IMMEDIATE
);

CREATE INDEX ix_envanter_devices_backup_group_id ON envanter.devices (backup_group_id);

CREATE INDEX ix_envanter_devices_site_id ON envanter.devices (site_id);

CREATE INDEX ix_envanter_devices_snmp_credential_id ON envanter.devices (snmp_credential_id);

CREATE INDEX ix_envanter_devices_discovery_scope_id ON envanter.devices (discovery_scope_id);

CREATE INDEX ix_envanter_devices_config_credential_id ON envanter.devices (config_credential_id);

CREATE INDEX ix_envanter_devices_config_approved_by ON envanter.devices (config_approved_by);

CREATE INDEX ix_envanter_devices_kind ON envanter.devices (kind);

CREATE INDEX ix_envanter_devices_base_snapshot_id ON envanter.devices (base_snapshot_id);

CREATE INDEX ix_envanter_devices_vrf_id ON envanter.devices (vrf_id);

CREATE TABLE envanter.discovery_scope_credentials (
	scope_id VARCHAR(36) NOT NULL, 
	credential_id VARCHAR(36) NOT NULL, 
	position INTEGER NOT NULL, 
	PRIMARY KEY (scope_id, credential_id), 
	UNIQUE (scope_id, position), 
	FOREIGN KEY(scope_id) REFERENCES envanter.discovery_scopes (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(credential_id) REFERENCES yonetim.credentials (id) DEFERRABLE INITIALLY IMMEDIATE
);

CREATE INDEX ix_envanter_discovery_scope_credentials_credential_id ON envanter.discovery_scope_credentials (credential_id);

CREATE TABLE ip_adres_yonetimi.vmware_nics (
	source_key VARCHAR(120) NOT NULL, 
	owner_key VARCHAR(190) NOT NULL, 
	nic_key VARCHAR(120) NOT NULL, 
	vm_id VARCHAR(36), 
	host_id VARCHAR(36), 
	network_id VARCHAR(36), 
	mac_address VARCHAR(17) NOT NULL, 
	port VARCHAR(120) NOT NULL, 
	observed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_vmware_nic UNIQUE (source_key, owner_key, nic_key), 
	CONSTRAINT ck_vmware_nic_owner CHECK ((vm_id IS NULL) <> (host_id IS NULL)), 
	FOREIGN KEY(vm_id) REFERENCES ip_adres_yonetimi.vmware_vms (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(host_id) REFERENCES ip_adres_yonetimi.vmware_hosts (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(network_id) REFERENCES ip_adres_yonetimi.vmware_networks (id) ON DELETE SET NULL DEFERRABLE INITIALLY IMMEDIATE
);

CREATE INDEX ix_ip_adres_yonetimi_vmware_nics_vm_id ON ip_adres_yonetimi.vmware_nics (vm_id);

CREATE INDEX ix_ip_adres_yonetimi_vmware_nics_host_id ON ip_adres_yonetimi.vmware_nics (host_id);

CREATE TABLE ip_adres_yonetimi.rack_placements (
	cabinet_id VARCHAR(36) NOT NULL, 
	device_id VARCHAR(36) NOT NULL, 
	start_unit INTEGER NOT NULL, 
	units INTEGER NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_rack_position CHECK (start_unit >= 1 AND units >= 1 AND start_unit + units - 1 <= 60), 
	FOREIGN KEY(cabinet_id) REFERENCES ip_adres_yonetimi.cabinets (id) DEFERRABLE INITIALLY IMMEDIATE, 
	UNIQUE (device_id), 
	FOREIGN KEY(device_id) REFERENCES envanter.devices (id) DEFERRABLE INITIALLY IMMEDIATE
);

CREATE INDEX ix_ip_adres_yonetimi_rack_placements_cabinet_id ON ip_adres_yonetimi.rack_placements (cabinet_id);

CREATE TABLE envanter.interfaces (
	device_id VARCHAR(36) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	if_index INTEGER, 
	mac_address VARCHAR(40) NOT NULL, 
	speed_bps NUMERIC(20, 0), 
	oper_status VARCHAR(20) NOT NULL, 
	description VARCHAR(400) NOT NULL, 
	is_managed BOOLEAN DEFAULT '0' NOT NULL, 
	is_deleted BOOLEAN DEFAULT '0' NOT NULL, 
	auto_add_excluded BOOLEAN DEFAULT '0' NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (device_id, name), 
	UNIQUE (device_id, if_index), 
	FOREIGN KEY(device_id) REFERENCES envanter.devices (id) DEFERRABLE INITIALLY IMMEDIATE
);

CREATE INDEX ix_envanter_interfaces_device_id ON envanter.interfaces (device_id);

CREATE TABLE envanter.network_source_states (
	device_id VARCHAR(36), 
	address VARCHAR(45) NOT NULL, 
	observed_at TIMESTAMP WITH TIME ZONE, 
	attempted_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	job_id VARCHAR(36), 
	healthy BOOLEAN NOT NULL, 
	error_class VARCHAR(80) NOT NULL, 
	entry_count INTEGER NOT NULL, 
	fdb_complete BOOLEAN NOT NULL, 
	fdb_at TIMESTAMP WITH TIME ZONE, 
	gateway_at TIMESTAMP WITH TIME ZONE, 
	neighbors_at TIMESTAMP WITH TIME ZONE, 
	interfaces_at TIMESTAMP WITH TIME ZONE, 
	identity_at TIMESTAMP WITH TIME ZONE, 
	lldp_complete BOOLEAN NOT NULL, 
	cdp_complete BOOLEAN NOT NULL, 
	neighbor_detail_failed VARCHAR(80) NOT NULL, 
	stp_port VARCHAR(120), 
	stp_root BOOLEAN, 
	stp_source VARCHAR(40) NOT NULL, 
	read_address VARCHAR(45) NOT NULL, 
	read_port INTEGER, 
	read_vrf VARCHAR(36) NOT NULL, 
	read_profile VARCHAR(36), 
	read_profile_at VARCHAR(40) NOT NULL, 
	read_adapter VARCHAR(40) NOT NULL, 
	read_config_port INTEGER, 
	read_trust BOOLEAN NOT NULL, 
	read_ssh_profile VARCHAR(36), 
	read_ssh_at VARCHAR(40), 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (device_id), 
	FOREIGN KEY(device_id) REFERENCES envanter.devices (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(job_id) REFERENCES operasyon.jobs (id) ON DELETE SET NULL DEFERRABLE INITIALLY IMMEDIATE
);

CREATE TABLE firmware.firmware_group_members (
	group_id VARCHAR(36) NOT NULL, 
	device_id VARCHAR(36) NOT NULL, 
	PRIMARY KEY (group_id, device_id), 
	CONSTRAINT uq_firmware_member_device UNIQUE (device_id), 
	FOREIGN KEY(group_id) REFERENCES firmware.firmware_groups (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(device_id) REFERENCES envanter.devices (id) DEFERRABLE INITIALLY IMMEDIATE
);

CREATE TABLE konfigurasyon.config_snapshots (
	device_id VARCHAR(36) NOT NULL, 
	job_id VARCHAR(36) NOT NULL, 
	fingerprint VARCHAR(64) NOT NULL, 
	encrypted_content TEXT NOT NULL, 
	changed BOOLEAN NOT NULL, 
	size_bytes INTEGER NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (job_id, device_id), 
	FOREIGN KEY(device_id) REFERENCES envanter.devices (id) DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(job_id) REFERENCES operasyon.jobs (id) DEFERRABLE INITIALLY IMMEDIATE
);

CREATE INDEX ix_konfigurasyon_config_snapshots_device_id ON konfigurasyon.config_snapshots (device_id);

CREATE INDEX ix_konfigurasyon_config_snapshots_job_id ON konfigurasyon.config_snapshots (job_id);

CREATE TABLE operasyon.alert_instances (
	rule_id VARCHAR(36) NOT NULL, 
	device_id VARCHAR(36) NOT NULL, 
	active_key VARCHAR(80), 
	state VARCHAR(20) NOT NULL, 
	severity VARCHAR(20) NOT NULL, 
	message VARCHAR(400) NOT NULL, 
	observed_value FLOAT NOT NULL, 
	resolved_at TIMESTAMP WITH TIME ZONE, 
	acknowledged_at TIMESTAMP WITH TIME ZONE, 
	acknowledged_by VARCHAR(36), 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_alert_state CHECK (state in ('pending','firing','resolved')), 
	FOREIGN KEY(rule_id) REFERENCES operasyon.alert_rules (id) DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(device_id) REFERENCES envanter.devices (id) DEFERRABLE INITIALLY IMMEDIATE, 
	UNIQUE (active_key), 
	FOREIGN KEY(acknowledged_by) REFERENCES yonetim.users (id) DEFERRABLE INITIALLY IMMEDIATE
);

CREATE INDEX ix_operasyon_alert_instances_device_id ON operasyon.alert_instances (device_id);

CREATE INDEX ix_operasyon_alert_instances_rule_id ON operasyon.alert_instances (rule_id);

CREATE TABLE operasyon.change_events (
	device_id VARCHAR(36), 
	kind VARCHAR(50) NOT NULL, 
	message VARCHAR(400) NOT NULL, 
	details JSONB NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(device_id) REFERENCES envanter.devices (id) DEFERRABLE INITIALLY IMMEDIATE
);

CREATE INDEX ix_operasyon_change_events_device_id ON operasyon.change_events (device_id);

CREATE INDEX ix_change_events_created_at ON operasyon.change_events (created_at DESC, id);

CREATE TABLE yonetim.access_group_devices (
	group_id VARCHAR(36) NOT NULL, 
	owner_id VARCHAR(36) NOT NULL, 
	device_id VARCHAR(36) NOT NULL, 
	PRIMARY KEY (group_id, device_id), 
	CONSTRAINT uq_access_group_user_device UNIQUE (owner_id, device_id), 
	CONSTRAINT fk_access_group_device_owner FOREIGN KEY(group_id, owner_id) REFERENCES yonetim.access_groups (id, owner_id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(device_id) REFERENCES envanter.devices (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE
);

CREATE INDEX ix_access_group_device_owner ON yonetim.access_group_devices (group_id, owner_id);

CREATE INDEX ix_yonetim_access_group_devices_device_id ON yonetim.access_group_devices (device_id);

CREATE TABLE envanter.gateway_bindings (
	device_id VARCHAR(36), 
	source_key VARCHAR(190) NOT NULL, 
	source_name VARCHAR(190) NOT NULL, 
	vrf_id VARCHAR(36) NOT NULL, 
	address VARCHAR(45) NOT NULL, 
	mac_address VARCHAR(17) NOT NULL, 
	if_index INTEGER NOT NULL, 
	present BOOLEAN NOT NULL, 
	observed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_gateway_fact UNIQUE (source_key, vrf_id, address, mac_address, if_index), 
	FOREIGN KEY(device_id) REFERENCES envanter.devices (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(vrf_id) REFERENCES ip_adres_yonetimi.vrfs (id) DEFERRABLE INITIALLY IMMEDIATE
);

CREATE INDEX ix_gateway_ip ON envanter.gateway_bindings (vrf_id, address);

CREATE INDEX ix_envanter_gateway_bindings_vrf_id ON envanter.gateway_bindings (vrf_id);

CREATE INDEX ix_envanter_gateway_bindings_device_id ON envanter.gateway_bindings (device_id);

CREATE TABLE ip_adres_yonetimi.vmware_addresses (
	nic_id VARCHAR(36) NOT NULL, 
	address VARCHAR(45) NOT NULL, 
	present BOOLEAN NOT NULL, 
	observed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_vmware_address UNIQUE (nic_id, address), 
	FOREIGN KEY(nic_id) REFERENCES ip_adres_yonetimi.vmware_nics (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE
);

CREATE INDEX ix_ip_adres_yonetimi_vmware_addresses_nic_id ON ip_adres_yonetimi.vmware_addresses (nic_id);

CREATE INDEX ix_vmware_ip ON ip_adres_yonetimi.vmware_addresses (address, present);

CREATE TABLE ip_adres_yonetimi.vmware_uplinks (
	nic_id VARCHAR(36) NOT NULL, 
	physical_nic_id VARCHAR(36) NOT NULL, 
	PRIMARY KEY (nic_id, physical_nic_id), 
	FOREIGN KEY(nic_id) REFERENCES ip_adres_yonetimi.vmware_nics (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(physical_nic_id) REFERENCES ip_adres_yonetimi.vmware_physical_nics (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE
);

CREATE TABLE ip_adres_yonetimi.vmware_nic_hints (
	physical_nic_id VARCHAR(36) NOT NULL, 
	protocol VARCHAR(8) NOT NULL, 
	chassis_id VARCHAR(190) NOT NULL, 
	device_id VARCHAR(36), 
	port_id VARCHAR(120) NOT NULL, 
	port_description VARCHAR(190) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(physical_nic_id) REFERENCES ip_adres_yonetimi.vmware_physical_nics (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(device_id) REFERENCES envanter.devices (id) ON DELETE SET NULL DEFERRABLE INITIALLY IMMEDIATE
);

CREATE INDEX ix_ip_adres_yonetimi_vmware_nic_hints_physical_nic_id ON ip_adres_yonetimi.vmware_nic_hints (physical_nic_id);

CREATE TABLE ip_adres_yonetimi.patch_ports (
	panel_id VARCHAR(36) NOT NULL, 
	position INTEGER NOT NULL, 
	number VARCHAR(40) NOT NULL, 
	device_id VARCHAR(36), 
	interface_id VARCHAR(36), 
	device_name VARCHAR(190) NOT NULL, 
	port_name VARCHAR(120) NOT NULL, 
	cable_model VARCHAR(30) NOT NULL, 
	fiber_mode VARCHAR(12) DEFAULT '' NOT NULL, 
	peer_port_id VARCHAR(36), 
	external_data JSONB DEFAULT '{}' NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_patch_peer_port UNIQUE (peer_port_id), 
	CONSTRAINT uq_patch_port_number UNIQUE (panel_id, number), 
	CONSTRAINT uq_patch_port_position UNIQUE (panel_id, position), 
	CONSTRAINT ck_patch_port_position CHECK (position >= 1 AND position <= 288), 
	CONSTRAINT ck_patch_cable_model CHECK (cable_model in ('','Cat5','Cat6','Cat7','OM3','OM4','Multimode MM','Singlemode SM')), 
	CONSTRAINT ck_patch_fiber_mode CHECK (fiber_mode in ('','multimode','singlemode')), 
	FOREIGN KEY(panel_id) REFERENCES ip_adres_yonetimi.patch_panels (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(device_id) REFERENCES envanter.devices (id) ON DELETE SET NULL DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(interface_id) REFERENCES envanter.interfaces (id) ON DELETE SET NULL DEFERRABLE INITIALLY IMMEDIATE, 
	CONSTRAINT fk_patch_peer_port FOREIGN KEY(peer_port_id) REFERENCES ip_adres_yonetimi.patch_ports (id) ON DELETE SET NULL DEFERRABLE INITIALLY IMMEDIATE
);

CREATE INDEX ix_ip_adres_yonetimi_patch_ports_device_id ON ip_adres_yonetimi.patch_ports (device_id);

CREATE INDEX ix_ip_adres_yonetimi_patch_ports_panel_id ON ip_adres_yonetimi.patch_ports (panel_id);

CREATE INDEX ix_ip_adres_yonetimi_patch_ports_interface_id ON ip_adres_yonetimi.patch_ports (interface_id);

CREATE TABLE ip_adres_yonetimi.ip_addresses (
	institution_id VARCHAR(36), 
	site_id VARCHAR(36), 
	sub_site_id VARCHAR(36), 
	device_id VARCHAR(36), 
	address VARCHAR(45) NOT NULL, 
	vrf_id VARCHAR(36) NOT NULL, 
	vlan_id VARCHAR(36) NOT NULL, 
	interface_id VARCHAR(36), 
	hostname VARCHAR(190) NOT NULL, 
	mac_address VARCHAR(17) DEFAULT '' NOT NULL, 
	operating_system VARCHAR(190) DEFAULT '' NOT NULL, 
	cabinet VARCHAR(120) DEFAULT '' NOT NULL, 
	location VARCHAR(190) DEFAULT '' NOT NULL, 
	is_gateway BOOLEAN DEFAULT '0' NOT NULL, 
	nic_teaming BOOLEAN DEFAULT '0' NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (vrf_id, address), 
	CONSTRAINT ck_ip_status CHECK (status in ('reserved','active','deprecated')), 
	FOREIGN KEY(institution_id) REFERENCES ip_adres_yonetimi.institutions (id) DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(site_id) REFERENCES ip_adres_yonetimi.sites (id) DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(sub_site_id) REFERENCES ip_adres_yonetimi.sites (id) DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(device_id) REFERENCES envanter.devices (id) DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(vrf_id) REFERENCES ip_adres_yonetimi.vrfs (id) DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(vlan_id) REFERENCES ip_adres_yonetimi.vlans (id) DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(interface_id) REFERENCES envanter.interfaces (id) DEFERRABLE INITIALLY IMMEDIATE
);

CREATE INDEX ix_ip_adres_yonetimi_ip_addresses_vrf_id ON ip_adres_yonetimi.ip_addresses (vrf_id);

CREATE INDEX ix_ip_adres_yonetimi_ip_addresses_site_id ON ip_adres_yonetimi.ip_addresses (site_id);

CREATE INDEX ix_ip_adres_yonetimi_ip_addresses_vlan_id ON ip_adres_yonetimi.ip_addresses (vlan_id);

CREATE INDEX ix_ip_adres_yonetimi_ip_addresses_device_id ON ip_adres_yonetimi.ip_addresses (device_id);

CREATE INDEX ix_ip_adres_yonetimi_ip_addresses_interface_id ON ip_adres_yonetimi.ip_addresses (interface_id);

CREATE INDEX ix_ip_adres_yonetimi_ip_addresses_sub_site_id ON ip_adres_yonetimi.ip_addresses (sub_site_id);

CREATE INDEX ix_ip_adres_yonetimi_ip_addresses_institution_id ON ip_adres_yonetimi.ip_addresses (institution_id);

CREATE TABLE firmware.firmware_targets (
	plan_id VARCHAR(36) NOT NULL, 
	device_id VARCHAR(36) NOT NULL, 
	image_id VARCHAR(36) NOT NULL, 
	stage INTEGER NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	phase VARCHAR(30) NOT NULL, 
	bank VARCHAR(12) NOT NULL, 
	previous_bank VARCHAR(12) NOT NULL, 
	previous_version VARCHAR(120) NOT NULL, 
	verified_version VARCHAR(120) NOT NULL, 
	snapshot_id VARCHAR(36), 
	active_device VARCHAR(36), 
	heartbeat_at TIMESTAMP WITH TIME ZONE, 
	evidence JSONB NOT NULL, 
	error_code VARCHAR(40) NOT NULL, 
	error VARCHAR(400) NOT NULL, 
	transfer_username VARCHAR(60), 
	transfer_secret_hash VARCHAR(64) NOT NULL, 
	transfer_name VARCHAR(100), 
	transfer_expires_at TIMESTAMP WITH TIME ZONE, 
	transfer_bytes BIGINT NOT NULL, 
	finished_at TIMESTAMP WITH TIME ZONE, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_fw_plan_device UNIQUE (plan_id, device_id), 
	CONSTRAINT ck_fw_target_stage CHECK (stage >= 0), 
	CONSTRAINT ck_fw_target_status CHECK (status in ('queued','running','checked','staged','succeeded','failed','attention','cancelled')), 
	FOREIGN KEY(plan_id) REFERENCES firmware.firmware_plans (id) DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(device_id) REFERENCES envanter.devices (id) DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(image_id) REFERENCES firmware.firmware_images (id) DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(snapshot_id) REFERENCES konfigurasyon.config_snapshots (id) DEFERRABLE INITIALLY IMMEDIATE, 
	UNIQUE (active_device), 
	UNIQUE (transfer_username), 
	UNIQUE (transfer_name)
);

CREATE INDEX ix_firmware_firmware_targets_plan_id ON firmware.firmware_targets (plan_id);

CREATE INDEX ix_firmware_firmware_targets_status ON firmware.firmware_targets (status);

CREATE INDEX ix_firmware_firmware_targets_device_id ON firmware.firmware_targets (device_id);

CREATE INDEX ix_firmware_firmware_targets_image_id ON firmware.firmware_targets (image_id);

CREATE TABLE envanter.discovery_reads (
	job_id VARCHAR(36) NOT NULL, 
	device_id VARCHAR(36), 
	address VARCHAR(45) NOT NULL, 
	source VARCHAR(20) NOT NULL, 
	failed BOOLEAN NOT NULL, 
	error_class VARCHAR(80) NOT NULL, 
	confidence FLOAT NOT NULL, 
	network_state_id VARCHAR(36), 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (job_id, address), 
	FOREIGN KEY(job_id) REFERENCES operasyon.jobs (id) DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(device_id) REFERENCES envanter.devices (id) DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(network_state_id) REFERENCES envanter.network_source_states (id) ON DELETE SET NULL DEFERRABLE INITIALLY IMMEDIATE
);

CREATE INDEX ix_envanter_discovery_reads_job_id ON envanter.discovery_reads (job_id);

CREATE INDEX ix_envanter_discovery_reads_network_state_id ON envanter.discovery_reads (network_state_id);

CREATE INDEX ix_envanter_discovery_reads_device_id ON envanter.discovery_reads (device_id);

CREATE TABLE envanter.mac_port_records (
	snapshot_id VARCHAR(36) NOT NULL, 
	vrf_id VARCHAR(36) NOT NULL, 
	vlan_vid INTEGER NOT NULL, 
	fdb_id INTEGER NOT NULL, 
	bridge_port INTEGER NOT NULL, 
	status VARCHAR(10) NOT NULL, 
	mac_address VARCHAR(17) NOT NULL, 
	port VARCHAR(190) NOT NULL, 
	if_index INTEGER NOT NULL, 
	observed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	present BOOLEAN NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_mac_port_fact UNIQUE (snapshot_id, fdb_id, mac_address, port), 
	FOREIGN KEY(snapshot_id) REFERENCES envanter.network_source_states (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(vrf_id) REFERENCES ip_adres_yonetimi.vrfs (id) DEFERRABLE INITIALLY IMMEDIATE
);

CREATE INDEX ix_envanter_mac_port_records_snapshot_id ON envanter.mac_port_records (snapshot_id);

CREATE INDEX ix_mac_port_lookup ON envanter.mac_port_records (vrf_id, vlan_vid, mac_address);

CREATE TABLE ip_adres_yonetimi.vmware_hint_addresses (
	hint_id VARCHAR(36) NOT NULL, 
	address VARCHAR(45) NOT NULL, 
	PRIMARY KEY (hint_id, address), 
	FOREIGN KEY(hint_id) REFERENCES ip_adres_yonetimi.vmware_nic_hints (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE
);

CREATE TABLE envanter.source_ports (
	state_id VARCHAR(36) NOT NULL, 
	if_index INTEGER, 
	name VARCHAR(190) NOT NULL, 
	description VARCHAR(400) NOT NULL, 
	alias VARCHAR(400) NOT NULL, 
	mac_address VARCHAR(40) NOT NULL, 
	admin_status VARCHAR(20) NOT NULL, 
	oper_status VARCHAR(20) NOT NULL, 
	speed_bps BIGINT, 
	aggregate VARCHAR(120) NOT NULL, 
	aggregate_type VARCHAR(40) NOT NULL, 
	aggregate_source VARCHAR(40) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_source_port_index UNIQUE (state_id, if_index), 
	FOREIGN KEY(state_id) REFERENCES envanter.network_source_states (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE
);

CREATE INDEX ix_envanter_source_ports_state_id ON envanter.source_ports (state_id);

CREATE TABLE envanter.source_vlan_fdb (
	state_id VARCHAR(36) NOT NULL, 
	vlan_vid INTEGER NOT NULL, 
	fdb_id INTEGER NOT NULL, 
	PRIMARY KEY (state_id, vlan_vid), 
	FOREIGN KEY(state_id) REFERENCES envanter.network_source_states (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE
);

CREATE TABLE envanter.source_bridge_ports (
	state_id VARCHAR(36) NOT NULL, 
	bridge_port INTEGER NOT NULL, 
	if_index INTEGER NOT NULL, 
	PRIMARY KEY (state_id, bridge_port), 
	FOREIGN KEY(state_id) REFERENCES envanter.network_source_states (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE
);

CREATE TABLE envanter.gateway_networks (
	state_id VARCHAR(36) NOT NULL, 
	if_index INTEGER NOT NULL, 
	address VARCHAR(45) NOT NULL, 
	prefix_length INTEGER NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_gateway_network UNIQUE (state_id, if_index, address, prefix_length), 
	FOREIGN KEY(state_id) REFERENCES envanter.network_source_states (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE
);

CREATE INDEX ix_envanter_gateway_networks_state_id ON envanter.gateway_networks (state_id);

CREATE TABLE envanter.source_unsupported_tables (
	state_id VARCHAR(36) NOT NULL, 
	name VARCHAR(80) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	row_count INTEGER NOT NULL, 
	error_code VARCHAR(80) NOT NULL, 
	attempted_at TIMESTAMP WITH TIME ZONE, 
	successful_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (state_id, name), 
	FOREIGN KEY(state_id) REFERENCES envanter.network_source_states (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE
);

CREATE TABLE envanter.device_source_identities (
	state_id VARCHAR(36) NOT NULL, 
	hostname VARCHAR(190) NOT NULL, 
	sys_description TEXT NOT NULL, 
	sys_object_id VARCHAR(190) NOT NULL, 
	uptime VARCHAR(190) NOT NULL, 
	ip_forwarding VARCHAR(10) NOT NULL, 
	vendor VARCHAR(190) NOT NULL, 
	model VARCHAR(190) NOT NULL, 
	serial VARCHAR(190) NOT NULL, 
	kind VARCHAR(40) NOT NULL, 
	software_version VARCHAR(190) NOT NULL, 
	location VARCHAR(190) NOT NULL, 
	system_name VARCHAR(190) NOT NULL, 
	vendor_source VARCHAR(40) NOT NULL, 
	model_source VARCHAR(40) NOT NULL, 
	kind_source VARCHAR(40) NOT NULL, 
	software_version_source VARCHAR(40) NOT NULL, 
	serial_source VARCHAR(40) NOT NULL, 
	system_name_source VARCHAR(40) NOT NULL, 
	location_source VARCHAR(40) NOT NULL, 
	PRIMARY KEY (state_id), 
	FOREIGN KEY(state_id) REFERENCES envanter.network_source_states (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE
);

CREATE TABLE ip_adres_yonetimi.ip_resolution_results (
	address_id VARCHAR(36) NOT NULL, 
	scope_address VARCHAR(45) NOT NULL, 
	scope_vrf VARCHAR(36) NOT NULL, 
	scope_vlan VARCHAR(36), 
	status VARCHAR(12) NOT NULL, 
	retained BOOLEAN NOT NULL, 
	cached_import BOOLEAN NOT NULL, 
	hostname_conflict BOOLEAN NOT NULL, 
	connection_type VARCHAR(40) NOT NULL, 
	started_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	completed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	last_success_at TIMESTAMP WITH TIME ZONE, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_ip_result_status CHECK (status in ('success','problem')), 
	UNIQUE (address_id), 
	FOREIGN KEY(address_id) REFERENCES ip_adres_yonetimi.ip_addresses (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE
);

CREATE TABLE firmware.firmware_events (
	id BIGSERIAL NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	target_id VARCHAR(36) NOT NULL, 
	kind VARCHAR(20) NOT NULL, 
	phase VARCHAR(30) NOT NULL, 
	title VARCHAR(160) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	command TEXT NOT NULL, 
	response TEXT NOT NULL, 
	truncated BOOLEAN NOT NULL, 
	finished_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_fw_event_status CHECK (status in ('info','started','succeeded','failed','sent')), 
	FOREIGN KEY(target_id) REFERENCES firmware.firmware_targets (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE
);

CREATE INDEX ix_fw_event_target_order ON firmware.firmware_events (target_id, id);

CREATE TABLE baglanti.neighbor_links (
	device_id VARCHAR(36) NOT NULL, 
	port_id VARCHAR(36) NOT NULL, 
	identity_key VARCHAR(64) NOT NULL, 
	remote_device_id VARCHAR(36), 
	manual_remote_name VARCHAR(190), 
	manual_remote_port VARCHAR(120), 
	manual_remote_device_id VARCHAR(36), 
	source VARCHAR(20) NOT NULL, 
	confidence FLOAT NOT NULL, 
	auto_add_excluded BOOLEAN DEFAULT '0' NOT NULL, 
	is_current BOOLEAN NOT NULL, 
	last_seen_at TIMESTAMP WITH TIME ZONE, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_neighbor_identity UNIQUE (device_id, port_id, identity_key), 
	FOREIGN KEY(device_id) REFERENCES envanter.devices (id) DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(port_id) REFERENCES envanter.source_ports (id) DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(remote_device_id) REFERENCES envanter.devices (id) DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(manual_remote_device_id) REFERENCES envanter.devices (id) DEFERRABLE INITIALLY IMMEDIATE
);

CREATE INDEX ix_baglanti_neighbor_links_remote_device_id ON baglanti.neighbor_links (remote_device_id);

CREATE INDEX ix_baglanti_neighbor_links_is_current ON baglanti.neighbor_links (is_current);

CREATE INDEX ix_baglanti_neighbor_links_device_id ON baglanti.neighbor_links (device_id);

CREATE TABLE ip_adres_yonetimi.dns_records (
	address_id VARCHAR(36) NOT NULL, 
	source_key VARCHAR(120) NOT NULL, 
	hostname VARCHAR(190) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_dns_record UNIQUE (address_id, source_key), 
	FOREIGN KEY(address_id) REFERENCES ip_adres_yonetimi.ip_addresses (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE
);

CREATE INDEX ix_ip_adres_yonetimi_dns_records_address_id ON ip_adres_yonetimi.dns_records (address_id);

CREATE TABLE ip_adres_yonetimi.ping_states (
	address_id VARCHAR(36) NOT NULL, 
	reachability VARCHAR(20) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (address_id), 
	FOREIGN KEY(address_id) REFERENCES ip_adres_yonetimi.ip_addresses (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE
);

CREATE TABLE ip_adres_yonetimi.ip_source_links (
	address_id VARCHAR(36) NOT NULL, 
	source VARCHAR(20) NOT NULL, 
	source_key VARCHAR(120) NOT NULL, 
	observed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	present BOOLEAN NOT NULL, 
	matched_by VARCHAR(40) NOT NULL, 
	dns_id VARCHAR(36), 
	ping_id VARCHAR(36), 
	dhcp_id VARCHAR(36), 
	vmware_id VARCHAR(36), 
	gateway_id VARCHAR(36), 
	network_id VARCHAR(36), 
	scope_address VARCHAR(45) NOT NULL, 
	scope_vrf VARCHAR(36) NOT NULL, 
	scope_vlan VARCHAR(36), 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (address_id, source, source_key), 
	FOREIGN KEY(address_id) REFERENCES ip_adres_yonetimi.ip_addresses (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(dns_id) REFERENCES ip_adres_yonetimi.dns_records (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(ping_id) REFERENCES ip_adres_yonetimi.ping_states (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(dhcp_id) REFERENCES ip_adres_yonetimi.dhcp_bindings (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(vmware_id) REFERENCES ip_adres_yonetimi.vmware_addresses (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(gateway_id) REFERENCES envanter.gateway_bindings (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(network_id) REFERENCES envanter.network_source_states (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE
);

CREATE INDEX ix_ip_adres_yonetimi_ip_source_links_address_id ON ip_adres_yonetimi.ip_source_links (address_id);

CREATE TABLE baglanti.lldp_neighbors (
	link_id VARCHAR(36) NOT NULL, 
	remote_name VARCHAR(190) NOT NULL, 
	remote_port VARCHAR(120) NOT NULL, 
	chassis_id VARCHAR(190) NOT NULL, 
	chassis_subtype INTEGER, 
	port_id VARCHAR(190) NOT NULL, 
	port_subtype INTEGER, 
	port_description VARCHAR(190) NOT NULL, 
	system_name VARCHAR(190) NOT NULL, 
	management_address VARCHAR(45) NOT NULL, 
	local_port_id VARCHAR(190) NOT NULL, 
	local_port_number VARCHAR(120) NOT NULL, 
	record_index VARCHAR(190) NOT NULL, 
	transport VARCHAR(30) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (link_id), 
	FOREIGN KEY(link_id) REFERENCES baglanti.neighbor_links (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE
);

CREATE TABLE baglanti.cdp_neighbors (
	link_id VARCHAR(36) NOT NULL, 
	remote_name VARCHAR(190) NOT NULL, 
	remote_port VARCHAR(120) NOT NULL, 
	device_id VARCHAR(190) NOT NULL, 
	device_id_hex VARCHAR(380) NOT NULL, 
	port_id VARCHAR(190) NOT NULL, 
	system_name VARCHAR(190) NOT NULL, 
	management_address VARCHAR(45) NOT NULL, 
	record_index VARCHAR(190) NOT NULL, 
	transport VARCHAR(30) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (link_id), 
	FOREIGN KEY(link_id) REFERENCES baglanti.neighbor_links (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE
);

CREATE TABLE ip_adres_yonetimi.ip_resolution_connections (
	result_id VARCHAR(36) NOT NULL, 
	neighbor_id VARCHAR(36), 
	mac_port_id VARCHAR(36), 
	vmware_nic_id VARCHAR(36), 
	source VARCHAR(40) NOT NULL, 
	confidence FLOAT NOT NULL, 
	primary_source VARCHAR(40) NOT NULL, 
	endpoint_identity VARCHAR(250) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_resolution_connection_ref CHECK ((CASE WHEN neighbor_id IS NOT NULL THEN 1 ELSE 0 END) + (CASE WHEN mac_port_id IS NOT NULL THEN 1 ELSE 0 END) + (CASE WHEN vmware_nic_id IS NOT NULL THEN 1 ELSE 0 END) = 1), 
	CONSTRAINT uq_resolution_neighbor UNIQUE (result_id, neighbor_id), 
	CONSTRAINT uq_resolution_mac_port UNIQUE (result_id, mac_port_id), 
	CONSTRAINT uq_resolution_vmware_nic UNIQUE (result_id, vmware_nic_id), 
	FOREIGN KEY(result_id) REFERENCES ip_adres_yonetimi.ip_resolution_results (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(neighbor_id) REFERENCES baglanti.neighbor_links (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(mac_port_id) REFERENCES envanter.mac_port_records (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(vmware_nic_id) REFERENCES ip_adres_yonetimi.vmware_nics (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE
);

CREATE INDEX ix_ip_adres_yonetimi_ip_resolution_connections_result_id ON ip_adres_yonetimi.ip_resolution_connections (result_id);

CREATE INDEX ix_ip_adres_yonetimi_ip_resolution_connections_neighbor_id ON ip_adres_yonetimi.ip_resolution_connections (neighbor_id);

CREATE INDEX ix_ip_adres_yonetimi_ip_resolution_connections_vmware_nic_id ON ip_adres_yonetimi.ip_resolution_connections (vmware_nic_id);

CREATE INDEX ix_ip_adres_yonetimi_ip_resolution_connections_mac_port_id ON ip_adres_yonetimi.ip_resolution_connections (mac_port_id);

CREATE TABLE ip_adres_yonetimi.ip_resolution_issues (
	result_id VARCHAR(36) NOT NULL, 
	position INTEGER NOT NULL, 
	source VARCHAR(40) NOT NULL, 
	code VARCHAR(120) NOT NULL, 
	message TEXT NOT NULL, 
	PRIMARY KEY (result_id, position), 
	FOREIGN KEY(result_id) REFERENCES ip_adres_yonetimi.ip_resolution_results (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE
);

CREATE TABLE ip_adres_yonetimi.ip_resolution_steps (
	result_id VARCHAR(36) NOT NULL, 
	position INTEGER NOT NULL, 
	source VARCHAR(40) NOT NULL, 
	status VARCHAR(40) NOT NULL, 
	at TIMESTAMP WITH TIME ZONE, 
	mode VARCHAR(20) NOT NULL, 
	device_id VARCHAR(36), 
	label VARCHAR(190) NOT NULL, 
	PRIMARY KEY (result_id, position), 
	FOREIGN KEY(result_id) REFERENCES ip_adres_yonetimi.ip_resolution_results (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(device_id) REFERENCES envanter.devices (id) ON DELETE SET NULL DEFERRABLE INITIALLY IMMEDIATE
);

CREATE TABLE ip_adres_yonetimi.ip_resolution_fields (
	result_id VARCHAR(36) NOT NULL, 
	field VARCHAR(30) NOT NULL, 
	source_link_id VARCHAR(36), 
	gateway_id VARCHAR(36), 
	source VARCHAR(40) NOT NULL, 
	PRIMARY KEY (result_id, field), 
	FOREIGN KEY(result_id) REFERENCES ip_adres_yonetimi.ip_resolution_results (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(source_link_id) REFERENCES ip_adres_yonetimi.ip_source_links (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE, 
	FOREIGN KEY(gateway_id) REFERENCES envanter.gateway_bindings (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE
);

CREATE INDEX ix_ip_adres_yonetimi_ip_resolution_fields_source_link_id ON ip_adres_yonetimi.ip_resolution_fields (source_link_id);

CREATE INDEX ix_ip_adres_yonetimi_ip_resolution_fields_gateway_id ON ip_adres_yonetimi.ip_resolution_fields (gateway_id);

ALTER TABLE envanter.devices ADD CONSTRAINT fk_device_base_snapshot FOREIGN KEY(base_snapshot_id) REFERENCES konfigurasyon.config_snapshots (id) DEFERRABLE INITIALLY IMMEDIATE;
