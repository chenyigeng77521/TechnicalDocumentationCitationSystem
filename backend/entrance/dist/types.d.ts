/**
 * 通用类型定义
 */
export interface FileInfo {
    id: string;
    originalName: string;
    originalPath: string;
    format: string;
    size: number;
    uploadTime: string;
    status: FileStatus;
    category?: string;
    tags?: string[];
}
export type FileStatus = 'pending' | 'uploading' | 'completed' | 'failed';
export interface UploadResult {
    success: boolean;
    files: FileInfo[];
    message?: string;
}
export interface StatsResult {
    success: boolean;
    totalFiles: number;
    stats: {
        fileCount: number;
        totalSize: number;
        uploadDir: string;
    };
}
//# sourceMappingURL=types.d.ts.map