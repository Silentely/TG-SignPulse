/** @type {import('next').NextConfig} */
const isProd = process.env.NODE_ENV === 'production';

const nextConfig = {
  output: isProd ? "export" : undefined,
  // distDir: "out",
};

if (!isProd) {
  nextConfig.rewrites = async () => [
      {
        source: "/api/:path*",
        destination: "http://127.0.0.1:8000/api/:path*",
      },
    ];
}

module.exports = nextConfig;
