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
        mutable std::mutex mutex_;

        static double validate_(double initial, const char* name) {
            if (initial > 0.0) return initial;
            throw std::invalid_argument(std::string(name) + " must be greater than zero");
        }

        static double now_() {
            using namespace std::chrono;
            return duration<double>(steady_clock::now().time_since_epoch()).count();
        }

        void refill_(Bucket& bucket, double now) const {
            const double elapsed = std::max(0.0, now - bucket.last);
            bucket.last = std::max(bucket.last, now);
            bucket.tokens = std::min(capacity_, bucket.tokens + rate_ * elapsed);
        }

        double retry_after_(double balance, double cost) const {
            return (cost - balance) / rate_;
        }

        public:

        Limiter(double capacity, double rate):
            capacity_(validate_(capacity, "capacity")), rate_(validate_(rate, "rate")) {}
        double capacity() const { return capacity_;}
        double rate() const { return rate_;}

        double peek(const std::string& key, double now) const {
            std::lock_guard lock(mutex_);
            auto it = buckets_.find(key);
            if (it == buckets_.end()) return capacity_;
            Bucket bucket = it->second;
            refill_(bucket, now);
            return bucket.tokens;
        }

        double peek(const std::string& key) const {return peek(key, now_());}

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

        Decision consume(const std::string& key, double cost) {return consume(key, cost, now_());}

        bool reset(const std::string& key) {
            std::lock_guard lock(mutex_);
            return buckets_.erase(key) == 1;
        }

        std::size_t size() const {
            std::lock_guard lock(mutex_);
            return buckets_.size();
        }

        std::size_t purge(double idle, double now) {
            std::lock_guard lock(mutex_);
            std::size_t counter = 0;
            for (auto it = buckets_.begin(); it != buckets_.end();) {
                Bucket bucket = it->second;
                refill_(bucket, now);
                if (now - it->second.last >= idle && bucket.tokens == capacity_) {
                    it = buckets_.erase(it);
                    ++counter;
                } else ++it;
            }
            return counter;
        }

        std::size_t purge(double idle) {return purge(idle, now_());}

    };
}
