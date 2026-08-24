import { useEffect, useState } from "react";
import { fetchSettings, saveSettings, type AppSettings } from "../api/settings";

/** The one shared "current profile" for the whole app, backed by the
 *  `resumeProfile` setting Jobs/the tailoring pipeline already read.
 *
 *  There's no global app-level state elsewhere in this codebase -- every
 *  page fetches its own data -- so this stays a small hook each page calls
 *  independently rather than a new Context, matching that convention.
 *
 *  `refreshKey` is for the one exception: something that's always mounted
 *  and visible (the sidebar) can't rely on "refetch when this tab becomes
 *  active" the way every other page does, since it's never inactive. Pass a
 *  value that changes whenever a switch happens elsewhere (see App.tsx's
 *  profileVersion) to make this hook's own instance refetch too. */
export function useActiveProfileSettings(active: boolean, refreshKey: unknown = null) {
  const [settings, setSettings] = useState<AppSettings | null>(null);

  useEffect(() => {
    if (!active) return;
    (async () => {
      try {
        setSettings(await fetchSettings());
      } catch {
        /* caller falls back to its own defaults on a transient failure */
      }
    })();
    // refreshKey is an intentional extra trigger, not a value read in the
    // effect body -- see the doc comment above.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, refreshKey]);

  /** Persists the shared active profile and returns the freshly
   *  profile-scoped settings (prompts included) from the same round trip. */
  const switchProfile = async (profileId: string): Promise<AppSettings> => {
    const updated = await saveSettings({ resumeProfile: profileId });
    setSettings(updated);
    return updated;
  };

  /** Any other settings/prompt patch, e.g. saving edited prompts. */
  const patchSettings = async (patch: Partial<AppSettings>): Promise<AppSettings> => {
    const updated = await saveSettings(patch);
    setSettings(updated);
    return updated;
  };

  return { settings, switchProfile, patchSettings };
}
