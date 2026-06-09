// MongoDB 初始化脚本 —— 为 deep_research 数据库创建应用用户
// 仅在数据库首次初始化时执行（/docker-entrypoint-initdb.d/）
// 用户密码通过同名环境变量注入，未设置时使用默认值（仅限本地开发）

db = db.getSiblingDB('deep_research');

const username = _getEnv('MONGO_APP_USERNAME') || 'deepresearch';
const password = _getEnv('MONGO_APP_PASSWORD') || 'deepresearch_dev';

print(`[init-mongo] Creating user "${username}" on database "deep_research"...`);

db.createUser({
    user: username,
    pwd:  password,
    roles: [
        { role: 'readWrite', db: 'deep_research' },
    ],
});

print('[init-mongo] Done.');
