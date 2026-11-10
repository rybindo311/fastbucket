#pragma once
#include <string>
#include <unordered_map>
#include <mutex>
#include <stdexcept>
#include <chrono>
#include <algorithm>


namespace fastbucket {
    struct Decision {
        bool allowed;
        double remaining;
        double retry_after;
    };

    class Limiter {
        private:

        const double capacity_;
        const double rate_;

        struct Bucket {
            double last;
            double tokens;
        };

        std::unordered_map<std::string, Bucket> buckets_;
        std::mutex mutex_;

        static double validate_(double initial, const char* name) {
            if (initial > 0.0) return initial;
            throw std::invalid_argument(std::string(name) + " must be greater than zero");
        }

        void refill_(Bucket& bucket, double now) const {
            const double elapsed = std::max(0.0, now - bucket.last);
            bucket.tokens = std::min(capacity_, bucket.tokens + rate_ * elapsed);
            bucket.last = now;
        }

        double retry_after_(double balance, double cost) const {
            return (cost - balance) / rate_;
        }

        public:

        Limiter(double capacity, double rate):
            capacity_(validate_(capacity, "capacity")), rate_(validate_(rate, "rate")) {}
        double capacity() const { return capacity_;}
        double rate() const { return rate_;}

        Decision consume(const std::string& key, double cost, double now) {
            validate_(cost, "cost");
            if (cost > capacity_) throw std::invalid_argument("cost greater than capacity");
            std::lock_guard lock(mutex_);

            auto it = buckets_.try_emplace(key, Bucket{now, capacity_}).first;
            Bucket& bucket = it->second;

            refill_(bucket, now);
            if (bucket.tokens < cost) return Decision{
                false,
                bucket.tokens,
                retry_after_(bucket.tokens, cost),
            };

            bucket.tokens -= cost;
            return Decision{
                true,
                bucket.tokens,
                0.0,
            };
        }

        Decision consume(const std::string& key, double cost) {
            using namespace std::chrono;
            double now = duration<double>(steady_clock::now().time_since_epoch()).count();
            return consume(key, cost, now);
        }
    };
}
