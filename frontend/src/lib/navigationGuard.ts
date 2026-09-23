// A single in-app navigation guard. A page with unsaved work registers a check
// that decides (usually by asking the user) whether leaving for a target path
// may proceed. App's navigate() consults it before every in-app navigation.
type NavigationGuard = (href: string) => boolean;

let activeGuard: NavigationGuard | null = null;

export function setNavigationGuard(guard: NavigationGuard): () => void {
  activeGuard = guard;
  return () => {
    if (activeGuard === guard) activeGuard = null;
  };
}

export function allowNavigation(href: string): boolean {
  return activeGuard ? activeGuard(href) : true;
}
