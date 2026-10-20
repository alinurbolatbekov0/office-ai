export interface RuntimeConfig {
  apiBaseUrl: string;
  sessionToken: string;
}

declare global {
  interface Window {
    pywebview?: {
      api: {
        get_runtime_config: () => Promise<RuntimeConfig>;
      };
    };
  }
}

export async function getRuntimeConfig(): Promise<RuntimeConfig> {
  if (!window.pywebview?.api) {
    await new Promise<void>((resolve, reject) => {
      const timeout = window.setTimeout(
        () => reject(new Error("Откройте Office AI через desktop launcher.")),
        10_000,
      );
      window.addEventListener(
        "pywebviewready",
        () => {
          window.clearTimeout(timeout);
          resolve();
        },
        { once: true },
      );
    });
  }

  if (!window.pywebview?.api) {
    throw new Error("Desktop bridge недоступен.");
  }

  return window.pywebview.api.get_runtime_config();
}
