type User =
  { role?: string; email?: string; ssh_access?: boolean } | null | undefined;

export const SUPER_ADMIN_EMAIL = "alisan.yildirim@fbu.edu.tr";
export const isSuperAdmin = (user: User) =>
  !!user &&
  user.role === "super_admin" &&
  user.email?.toLowerCase() === SUPER_ADMIN_EMAIL;
export const hasAdminAccess = (user: User) =>
  user?.role === "admin" || isSuperAdmin(user);
export const canOperate = (user: User) =>
  user?.role === "operator" || hasAdminAccess(user);
export const canSSH = (user: User) => isSuperAdmin(user) || !!user?.ssh_access;
