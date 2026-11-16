type User =
  | {
      role?: string;
      email?: string;
      ssh_access?: boolean;
      auth_source?: string;
    }
  | null
  | undefined;

export const SUPER_ADMIN_EMAIL = "alisan.yildirim@fbu.edu.tr";
export const isRecoveryOwner = (user: User) =>
  !!user &&
  user.auth_source !== "saml" &&
  user.email?.toLowerCase() === SUPER_ADMIN_EMAIL;
export const isSuperAdmin = (user: User) => user?.role === "super_admin";
export const hasAdminAccess = (user: User) =>
  user?.role === "admin" || isSuperAdmin(user);
export const canOperate = (user: User) =>
  user?.role === "operator" || hasAdminAccess(user);
export const canSSH = (user: User) => isSuperAdmin(user) || !!user?.ssh_access;
