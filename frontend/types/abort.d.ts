declare global {
  interface AbortSignal {
    aborted: boolean;
    reason: any;
    addEventListener(type: 'abort', listener: () => void): void;
    removeEventListener(type: 'abort', listener: () => void): void;
    throwIfAborted(): void;
  }
}

export {};
