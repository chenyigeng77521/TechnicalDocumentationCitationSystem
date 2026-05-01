declare module 'csv-parser' {
  import { Readable } from 'stream';

  interface Options {
    separator?: string;
    quote?: string;
    escape?: string;
    headers?: string[] | boolean;
    mapHeaders?: (args: { header: string; index: number }) => string | null;
    mapValues?: (args: { header: string; index: number; value: string }) => any;
    strict?: boolean;
    skipLines?: number;
    maxRows?: number;
    skipComments?: string | boolean;
  }

  function csvParser(options?: Options): (stream: Readable) => NodeJS.ReadableStream & { on(event: string, handler: (row: any) => void): void };

  export = csvParser;
}
