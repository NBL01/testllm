/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // The job board is the home screen; a separate landing page only repeated its links.
  async redirects() {
    return [{ source: "/", destination: "/jobs", permanent: false }];
  }
};

export default nextConfig;
