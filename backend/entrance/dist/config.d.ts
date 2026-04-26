/**
 * 项目配置文件
 * 所有配置通过 getter 延迟读取环境变量
 */
export declare const config: {
    upload: {
        uploadDir: string;
        maxFileSize: number;
        allowedFormats: string[];
        maxFiles: number;
    };
    readonly server: {
        port: number;
        host: string;
    };
    readonly firstlayer: {
        url: string;
        enabled: boolean;
        timeout: number;
    };
    readonly questionFilter: {
        url: string;
        enabled: boolean;
        timeout: number;
    };
};
export default config;
//# sourceMappingURL=config.d.ts.map